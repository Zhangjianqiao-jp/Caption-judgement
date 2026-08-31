from __future__ import annotations

from collections import Counter, defaultdict
import json
import re
from typing import Any, Iterable

from .contracts import validate_generations


GENERIC = re.compile(r"\b(?:pov|bro|meanwhile|nobody|when you|that moment when)\b|[💀😂🤣]", re.I)


def audit_generations(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    validation = validate_generations(rows)
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exact: dict[tuple[str, str | None, str], set[str]] = defaultdict(set)
    for row in rows:
        by_system[row["system_id"]].append(row)
        exact[(row["image_id"], row.get("target_culture"), " ".join(row["caption"].casefold().split()))].add(row["system_id"])
    summaries = []
    for system, values in sorted(by_system.items()):
        words = [len(str(row["caption"]).split()) for row in values]
        unique = len({" ".join(row["caption"].casefold().split()) for row in values})
        summaries.append({
            "system": system, "captions": len(values), "mean_words": sum(words) / len(words),
            "min_words": min(words), "max_words": max(words),
            "unique_rate": unique / len(values),
            "empty_output_rate": sum(row["caption"] == "[EMPTY OUTPUT]" for row in values) / len(values),
            "generic_template_rate": sum(bool(GENERIC.search(row["caption"])) for row in values) / len(values),
            "exclamation_rate": sum("!" in row["caption"] for row in values) / len(values),
        })
    cross = [
        {"image_id": key[0], "target_culture": key[1], "caption": key[2], "systems": sorted(systems)}
        for key, systems in exact.items() if len(systems) > 1
    ]
    return {"schema_version": 1, "validation": validation, "systems": summaries,
            "cross_system_exact_duplicates": cross, "cross_system_duplicate_count": len(cross)}


def audit_blinding(packets: Iterable[dict[str, Any]], mapping_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    packets, mapping_rows = list(packets), list(mapping_rows)
    mapping = {row["blind_id"]: row for row in mapping_rows}
    if {row["blind_id"] for row in packets} != set(mapping):
        raise ValueError("public packet/private mapping blind_id coverage mismatch")
    systems = {row["reference"] for row in mapping_rows} | {row["challenger"] for row in mapping_rows}
    leakage = []
    for packet in packets:
        # A caption may legitimately contain a word equal to a system alias;
        # blinding concerns packet metadata, not model-generated content.
        metadata_only = {key: value for key, value in packet.items() if key not in {"group_A", "group_B"}}
        encoded = json.dumps(metadata_only, ensure_ascii=False)
        leakage.extend(system for system in systems if system in encoded)
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping_rows: pairs[row["mirror_pair_id"]].append(row)
    malformed = []
    for pair_id, values in pairs.items():
        if len(values) == 2:
            a, b = sorted(values, key=lambda row: row["orientation"])
            packet_a = next(row for row in packets if row["blind_id"] == a["blind_id"])
            packet_b = next(row for row in packets if row["blind_id"] == b["blind_id"])
            same_candidates = (
                set(packet_a["group_A"]) == set(packet_b["group_B"])
                and set(packet_a["group_B"]) == set(packet_b["group_A"])
            )
            same_seeds = set(a["seeds_A"]) == set(b["seeds_B"]) and set(a["seeds_B"]) == set(b["seeds_A"])
            if ({a["orientation"], b["orientation"]} != {0, 1}
                    or a["condition_A"] != b["condition_B"] or a["condition_B"] != b["condition_A"]
                    or not same_candidates or not same_seeds):
                malformed.append(pair_id)
        elif len(values) != 1:
            malformed.append(pair_id)
    if leakage or malformed:
        raise ValueError(f"blinding audit failed: leakage={sorted(set(leakage))}, malformed={malformed[:10]}")
    return {"schema_version": 1, "packets": len(packets), "mirror_pairs": len(pairs),
            "system_identifier_leaks": 0, "malformed_mirror_pairs": 0, "passed": True}
