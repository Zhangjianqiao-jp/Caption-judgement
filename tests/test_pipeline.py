from __future__ import annotations

import hashlib

import pytest

from caption_judgement.aggregate import aggregate_ratings
from caption_judgement.adapters import adapt_humor_generator_v35
from caption_judgement.audit import audit_blinding
from caption_judgement.contracts import DIMENSIONS, validate_generations
from caption_judgement.packet import build_blind_packets
from caption_judgement.prompts import prompt_sha256
from caption_judgement.cli import main
from caption_judgement.io import read_jsonl, write_json, write_jsonl


def generations():
    digest = hashlib.sha256(b"image").hexdigest()
    rows = []
    for system in ("sft", "dpo"):
        for image in ("i1", "i2", "i3"):
            for seed in (1, 2, 3):
                rows.append({"system_id": system, "image_id": image, "image_path": f"/data/{image}.jpg",
                             "image_sha256": digest, "split": "test", "target_culture": None,
                             "caption": f"A caption for {image}, version {seed}, variant {system == 'dpo'}",
                             "generation_seed": seed})
    return rows


def decision(row, winner_system=None, always_a=False):
    if always_a: choice = "A"
    elif winner_system is None: choice = "Tie"
    else: choice = "A" if row["condition_A"] == winner_system else "B"
    dims = {name: (None if name in {"cultural_fit", "stereotype_risk"} else 4) for name in DIMENSIONS}
    n = row["group_size"]
    return {"overall": choice, "best_pick": choice, "best_A_index": 1, "best_B_index": 1,
            "absolute_A": "weak", "absolute_B": "weak", "candidate_labels_A": ["weak"]*n,
            "candidate_labels_B": ["weak"]*n, "dimensions_A": dims, "dimensions_B": dict(dims), "evidence": "visible detail"}


def payload(mapping, mode):
    return {"rater_id": mode, "judge_metadata": {"provider": "test", "model": "test",
            "version_or_date": "fixed", "temperature": 0, "prompt_sha256": prompt_sha256()},
            "decisions": {row["blind_id"]: decision(row, winner_system="dpo" if mode == "dpo" else None,
                                                       always_a=mode == "position") for row in mapping}}


def test_packet_is_deterministic_blind_and_mirrored():
    args = (generations(), [("sft", "dpo")])
    a = build_blind_packets(*args, secret=b"0123456789abcdef", group_size=3)
    b = build_blind_packets(*args, secret=b"0123456789abcdef", group_size=3)
    assert a == b
    packets, mapping = a
    assert len(packets) == 6
    assert not any(key in packet for packet in packets for key in ("system_id", "reference", "challenger", "condition_A"))
    assert audit_blinding(packets, mapping)["passed"]


def test_challenger_wins_after_mirror_collapse():
    _, mapping = build_blind_packets(generations(), [("sft", "dpo")], secret=b"0123456789abcdef")
    result = aggregate_ratings(mapping, [payload(mapping, "dpo")], bootstrap_replicates=200)
    assert all(row["challenger_win_rate_ties_half"] == 1.0 for row in result["relative"])
    assert result["position_diagnostics"]["mirror_system_choice_consistency"] == 1.0


def test_always_a_position_bias_collapses_to_tie():
    _, mapping = build_blind_packets(generations(), [("sft", "dpo")], secret=b"0123456789abcdef")
    result = aggregate_ratings(mapping, [payload(mapping, "position")], bootstrap_replicates=200)
    assert all(row["challenger_win_rate_ties_half"] == 0.5 for row in result["relative"])
    assert result["position_diagnostics"]["raw_A_rate_excluding_ties"] == 1.0
    assert result["position_diagnostics"]["mirror_system_choice_consistency"] == 0.0


def test_culture_is_part_of_unit_and_incomplete_coverage_fails():
    rows = generations()
    extra = dict(rows[0]); extra["target_culture"] = "Japan"; extra["caption"] = "文化的な冗談"
    rows.append(extra)
    validate_generations(rows)
    with pytest.raises(ValueError, match="image mismatch"):
        build_blind_packets(rows, [("sft", "dpo")], secret=b"0123456789abcdef")


def test_v35_adapter_preserves_interface(tmp_path):
    image = tmp_path / "cartoon.png"; image.write_bytes(b"image")
    source = [{"receiver": "sft", "condition": "typed", "cluster_id": "nycc_1",
               "image": str(image), "caption": "A laboratory joke.", "generation_seed": 7,
               "split": "internal_test"}]
    row = adapt_humor_generator_v35(source)[0]
    assert row["system_id"] == "sft::typed"
    assert row["image_id"] == "nycc_1"
    assert row["image_sha256"] == hashlib.sha256(b"image").hexdigest()


def test_v35_cli_closed_loop(tmp_path):
    image = tmp_path / "cartoon.png"; image.write_bytes(b"image")
    source = []
    for condition in ("text", "typed"):
        for seed in (1, 2, 3):
            source.append({"receiver": "sft", "condition": condition, "cluster_id": "nycc_1",
                           "image": str(image), "caption": f"caption {condition} {seed}",
                           "generation_seed": seed, "split": "test"})
    raw = tmp_path / "raw.jsonl"; canonical = tmp_path / "canonical.jsonl"
    public = tmp_path / "packets.jsonl"; private = tmp_path / "mapping.jsonl"
    manifest = tmp_path / "manifest.json"; secret = tmp_path / "secret"
    prompts = tmp_path / "prompts.jsonl"; audit = tmp_path / "audit.json"
    diversity = tmp_path / "diversity.json"; rating = tmp_path / "rating.json"
    aggregate = tmp_path / "aggregate.json"; report = tmp_path / "report.md"
    write_jsonl(raw, source); secret.write_bytes(b"0123456789abcdef")
    main(["adapt", "--input", str(raw), "--output", str(canonical)])
    main(["build-packets", "--generations", str(canonical), "--comparison", "sft::text=>sft::typed",
          "--secret-file", str(secret), "--public", str(public), "--private", str(private), "--manifest", str(manifest)])
    main(["render-prompts", "--packets", str(public), "--output", str(prompts)])
    main(["audit", "--generations", str(canonical), "--packets", str(public), "--mapping", str(private), "--output", str(audit)])
    main(["diversity", "--generations", str(canonical), "--output", str(diversity)])
    mapping = read_jsonl(private)
    write_json(rating, payload(mapping, "dpo"))
    main(["aggregate", "--mapping", str(private), "--ratings", str(rating), "--bootstrap", "100", "--output", str(aggregate)])
    main(["report", "--aggregate", str(aggregate), "--audit", str(audit), "--diversity", str(diversity), "--output", str(report)])
    assert "Humorous Caption Evaluation Report" in report.read_text()
