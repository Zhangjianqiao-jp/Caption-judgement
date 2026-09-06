from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .adapters import adapt_auto
from .aggregate import aggregate_ratings
from .audit import audit_blinding, audit_generations
from .contracts import DIMENSIONS, validate_generations
from .diversity import summarize_diversity
from .io import read_json, read_jsonl, sha256_file, write_json, write_jsonl
from .packet import build_blind_packets, packet_manifest, parse_comparison
from .prompts import RUBRIC_VERSION, prompt_sha256, render_judge_prompt
from .provenance import provenance_sha256, validate_provenance, validate_rating_provenance
from .homer import summarize_homer_pass_at_k
from .report import render_markdown, save_plots


def _load_rows(path: str):
    return read_jsonl(path) if path.endswith(".jsonl") else read_json(path)


def _cmd_adapt(args):
    rows = adapt_auto(_load_rows(args.input), verify_images=not args.skip_image_check)
    validate_generations(rows, check_images=not args.skip_image_check)
    write_jsonl(args.output, rows)


def _cmd_validate(args):
    print(validate_generations(read_jsonl(args.input), check_images=args.check_images))


def _cmd_build(args):
    rows = read_jsonl(args.generations)
    secret = Path(args.secret_file).read_bytes().strip()
    packets, mapping = build_blind_packets(
        rows, [parse_comparison(value) for value in args.comparison], secret=secret,
        group_size=args.group_size, family=args.family, mirror_sides=not args.no_mirror,
        rubric_version=RUBRIC_VERSION,
    )
    write_jsonl(args.public, packets); write_jsonl(args.private, mapping)
    provenance = read_json(args.provenance) if args.provenance else None
    if provenance is not None:
        errors = validate_provenance(provenance)
        if errors:
            raise ValueError("invalid provenance:\n" + "\n".join(errors))
        if provenance.get("source_generations_sha256") != sha256_file(args.generations):
            raise ValueError("provenance.source_generations_sha256 does not match --generations")
    manifest = packet_manifest(packets, mapping, source_sha256=sha256_file(args.generations), provenance=provenance)
    manifest["rubric_sha256"] = prompt_sha256(); write_json(args.manifest, manifest)


def _cmd_prompts(args):
    write_jsonl(args.output, ({"blind_id": row["blind_id"], "prompt": render_judge_prompt(row)} for row in read_jsonl(args.packets)))


def _cmd_template(args):
    decisions = {}
    for packet in read_jsonl(args.packets):
        n = len(packet["group_A"]); dims = {name: None for name in DIMENSIONS}
        decisions[packet["blind_id"]] = {
            "overall": None, "best_pick": None, "best_A_index": None, "best_B_index": None,
            "absolute_A": None, "absolute_B": None,
            "candidate_labels_A": [None]*n, "candidate_labels_B": [None]*n,
            "dimensions_A": dims, "dimensions_B": dict(dims), "evidence": "",
        }
    write_json(args.output, {"schema_version": 1, "rater_id": args.rater_id,
        "judge_metadata": {"provider": "", "model": "", "version_or_date": "", "temperature": 0,
                           "prompt_sha256": prompt_sha256()}, "decisions": decisions})


def _cmd_audit(args):
    result = {"generations": audit_generations(read_jsonl(args.generations))}
    if args.packets and args.mapping:
        result["blinding"] = audit_blinding(read_jsonl(args.packets), read_jsonl(args.mapping))
    write_json(args.output, result)


def _cmd_aggregate(args):
    provenance = read_json(args.provenance) if args.provenance else None
    if provenance is not None:
        errors = validate_provenance(provenance)
        if errors:
            raise ValueError("invalid provenance:\n" + "\n".join(errors))
    result = aggregate_ratings(read_jsonl(args.mapping), [read_json(path) for path in args.ratings],
                               bootstrap_seed=args.seed, bootstrap_replicates=args.bootstrap,
                               provenance=provenance)
    write_json(args.output, result)


def _cmd_homer_pass_at_k(args):
    provenance = read_json(args.provenance) if args.provenance else None
    if provenance is not None:
        errors = validate_provenance(provenance)
        if errors:
            raise ValueError("invalid provenance:\n" + "\n".join(errors))
    result = summarize_homer_pass_at_k(
        read_jsonl(args.records), ks=tuple(args.k), bootstrap_seed=args.seed,
        bootstrap_replicates=args.bootstrap, provenance=provenance,
    )
    write_json(args.output, result)


def _cmd_diversity(args):
    model = None
    if args.sbert_model:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("install caption-judgement[semantic] for SBERT diversity") from exc
        model = SentenceTransformer(args.sbert_model)
    write_json(args.output, summarize_diversity(read_jsonl(args.generations), args.min_candidates, model))


def _cmd_report(args):
    aggregate = read_json(args.aggregate)
    audit = read_json(args.audit) if args.audit else None
    diversity = read_json(args.diversity) if args.diversity else None
    Path(args.output).write_text(render_markdown(aggregate, audit, diversity), encoding="utf-8")
    if args.plots_dir: save_plots(aggregate, args.plots_dir)


def build_parser():
    parser = argparse.ArgumentParser(prog="caption-judge")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("adapt"); p.add_argument("--input", required=True); p.add_argument("--output", required=True); p.add_argument("--skip-image-check", action="store_true"); p.set_defaults(func=_cmd_adapt)
    p = sub.add_parser("validate"); p.add_argument("--input", required=True); p.add_argument("--check-images", action="store_true"); p.set_defaults(func=_cmd_validate)
    p = sub.add_parser("build-packets"); p.add_argument("--generations", required=True); p.add_argument("--comparison", action="append", required=True); p.add_argument("--secret-file", required=True); p.add_argument("--group-size", type=int, default=3); p.add_argument("--family", default="primary"); p.add_argument("--no-mirror", action="store_true"); p.add_argument("--provenance"); p.add_argument("--public", required=True); p.add_argument("--private", required=True); p.add_argument("--manifest", required=True); p.set_defaults(func=_cmd_build)
    p = sub.add_parser("render-prompts"); p.add_argument("--packets", required=True); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_prompts)
    p = sub.add_parser("rating-template"); p.add_argument("--packets", required=True); p.add_argument("--rater-id", required=True); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_template)
    p = sub.add_parser("audit"); p.add_argument("--generations", required=True); p.add_argument("--packets"); p.add_argument("--mapping"); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_audit)
    p = sub.add_parser("aggregate"); p.add_argument("--mapping", required=True); p.add_argument("--ratings", nargs="+", required=True); p.add_argument("--provenance"); p.add_argument("--seed", type=int, default=20250308); p.add_argument("--bootstrap", type=int, default=10000); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_aggregate)
    p = sub.add_parser("homer-pass-at-k"); p.add_argument("--records", required=True); p.add_argument("--k", type=int, nargs="+", default=[1, 3, 5]); p.add_argument("--provenance"); p.add_argument("--seed", type=int, default=20250308); p.add_argument("--bootstrap", type=int, default=10000); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_homer_pass_at_k)
    p = sub.add_parser("diversity"); p.add_argument("--generations", required=True); p.add_argument("--min-candidates", type=int, default=2); p.add_argument("--sbert-model"); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_diversity)
    p = sub.add_parser("report"); p.add_argument("--aggregate", required=True); p.add_argument("--audit"); p.add_argument("--diversity"); p.add_argument("--plots-dir"); p.add_argument("--output", required=True); p.set_defaults(func=_cmd_report)
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        args.func(args)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); raise SystemExit(2)


if __name__ == "__main__": main()
