from __future__ import annotations

import hashlib
import hmac
from typing import Any, Iterable

from .contracts import index_generations, validate_generations
from .io import canonical_json, sha256_bytes


def _digest(secret: bytes, *values: Any) -> str:
    message = canonical_json(values).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _ordered(values: Iterable[Any], secret: bytes, namespace: str) -> list[Any]:
    return sorted(values, key=lambda value: _digest(secret, namespace, value))


def parse_comparison(value: str) -> tuple[str, str]:
    pieces = value.split("=>") if "=>" in value else value.split(":")
    if len(pieces) != 2 or not all(piece.strip() for piece in pieces):
        raise ValueError(f"comparison must be REFERENCE=>CHALLENGER (or simple REF:CHAL), got {value!r}")
    if pieces[0] == pieces[1]:
        raise ValueError("reference and challenger must differ")
    return pieces[0], pieces[1]


def build_blind_packets(
    generations: Iterable[dict[str, Any]], comparisons: Iterable[tuple[str, str]], *,
    secret: bytes, group_size: int = 3, family: str = "primary",
    mirror_sides: bool = True, rubric_version: str = "humor-caption-v1",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = list(generations)
    validate_generations(rows)
    if len(secret) < 16:
        raise ValueError("blind secret must contain at least 16 bytes")
    if group_size < 1:
        raise ValueError("group_size must be positive")
    comparisons = list(comparisons)
    if not comparisons:
        raise ValueError("at least one explicit comparison is required")
    grouped = index_generations(rows)
    systems = {row["system_id"] for row in rows}
    packets, mapping = [], []
    for reference, challenger in comparisons:
        if reference not in systems or challenger not in systems:
            raise ValueError(f"comparison references unknown system: {reference}:{challenger}")
        reference_units = {(image, culture) for system, image, culture in grouped if system == reference}
        challenger_units = {(image, culture) for system, image, culture in grouped if system == challenger}
        if reference_units != challenger_units:
            raise ValueError(
                f"image mismatch for {reference}:{challenger}: "
                f"reference={len(reference_units)}, challenger={len(challenger_units)}"
            )
        for image_id, culture in sorted(reference_units, key=lambda item: (item[0], item[1] or "")):
            by_system = {
                system: {int(row["generation_seed"]): row for row in grouped[(system, image_id, culture)]}
                for system in (reference, challenger)
            }
            common_seeds = set(by_system[reference]) & set(by_system[challenger])
            if len(common_seeds) < group_size:
                raise ValueError(
                    f"{image_id}/{reference}:{challenger} has {len(common_seeds)} shared seeds, "
                    f"needs {group_size}"
                )
            selected = _ordered(
                common_seeds, secret,
                f"seed-selection:{family}:{reference}:{challenger}:{image_id}:{culture or '-'}"
            )[:group_size]
            candidates = {
                system: [by_system[system][seed] for seed in selected]
                for system in (reference, challenger)
            }
            metadata_keys = ("image_path", "image_sha256", "split", "target_culture")
            meta = {key: candidates[reference][0].get(key) for key in metadata_keys}
            for system in (reference, challenger):
                if any(any(row.get(key) != meta[key] for key in metadata_keys) for row in candidates[system]):
                    raise ValueError(f"metadata mismatch within paired candidates for {image_id}")
            pair_id = _digest(secret, "pair", family, reference, challenger, image_id, culture)[:24]
            first = (reference, challenger)
            if int(_digest(secret, "first-side", pair_id), 16) % 2:
                first = tuple(reversed(first))
            orientations = [first, tuple(reversed(first))] if mirror_sides else [first]
            for orientation, (system_a, system_b) in enumerate(orientations):
                blind_id = _digest(secret, "blind", pair_id, orientation)[:24]
                ordered = {}
                for side, system in (("A", system_a), ("B", system_b)):
                    ordered[side] = _ordered(
                        candidates[system], secret, f"candidate-order:{blind_id}:{side}"
                    )
                packets.append({
                    "schema_version": 1,
                    "blind_id": blind_id,
                    "image_id": image_id,
                    "image_path": meta["image_path"],
                    "target_culture": meta["target_culture"],
                    "rubric_version": rubric_version,
                    "group_A": [row["caption"] for row in ordered["A"]],
                    "group_B": [row["caption"] for row in ordered["B"]],
                })
                mapping.append({
                    "schema_version": 1,
                    "blind_id": blind_id,
                    "mirror_pair_id": pair_id,
                    "orientation": orientation,
                    "comparison_family": family,
                    "reference": reference,
                    "challenger": challenger,
                    "condition_A": system_a,
                    "condition_B": system_b,
                    "image_id": image_id,
                    "image_path": meta["image_path"],
                    "image_sha256": meta["image_sha256"],
                    "split": meta["split"],
                    "target_culture": meta["target_culture"],
                    "group_size": group_size,
                    "seeds_A": [int(row["generation_seed"]) for row in ordered["A"]],
                    "seeds_B": [int(row["generation_seed"]) for row in ordered["B"]],
                    "rubric_version": rubric_version,
                })
    packets.sort(key=lambda row: row["blind_id"])
    mapping.sort(key=lambda row: row["blind_id"])
    return packets, mapping


def packet_manifest(
    packets: list[dict[str, Any]], mapping: list[dict[str, Any]], *, source_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "packets": len(packets),
        "unique_images": len({row["image_id"] for row in mapping}),
        "comparisons": sorted({
            f"{row['comparison_family']}:{row['reference']}:{row['challenger']}"
            for row in mapping
        }),
        "mirror_orientations": sorted({row["orientation"] for row in mapping}),
        "source_generations_sha256": source_sha256,
        "public_packet_sha256": sha256_bytes(
            "".join(canonical_json(row) + "\n" for row in packets).encode("utf-8")
        ),
        "private_mapping_sha256": sha256_bytes(
            "".join(canonical_json(row) + "\n" for row in mapping).encode("utf-8")
        ),
    }
