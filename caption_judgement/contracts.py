from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
from typing import Any, Iterable


RELATIVE_CHOICES = {"A", "B", "Tie"}
ABSOLUTE_LABELS = {"good", "weak", "bad"}
ABSOLUTE_VALUE = {"bad": 0.0, "weak": 0.5, "good": 1.0}
DIMENSIONS = (
    "humor", "image_grounding", "image_relevance", "originality", "specificity", "fluency",
    "hallucination_severity",
    "cultural_fit", "stereotype_risk",
)
OPTIONAL_DIMENSIONS = {"cultural_fit", "stereotype_risk"}
CORE_DIMENSIONS = tuple(name for name in DIMENSIONS if name not in OPTIONAL_DIMENSIONS)
HASH = re.compile(r"[0-9a-f]{64}")


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def validate_generations(rows: Iterable[dict[str, Any]], *, check_images: bool = False) -> dict[str, Any]:
    rows = list(rows)
    if not rows:
        raise ValueError("generation file is empty")
    seen: set[tuple[str, str, str | None, int]] = set()
    image_metadata: dict[str, tuple[Any, ...]] = {}
    per_system_image: Counter[tuple[str, str, str | None]] = Counter()
    systems, images, splits, cultures = set(), set(), set(), set()
    errors = []
    for index, row in enumerate(rows, 1):
        try:
            system = _text(row, "system_id")
            image_id = _text(row, "image_id")
            image_path = _text(row, "image_path")
            image_sha = _text(row, "image_sha256")
            split = _text(row, "split")
            caption = _text(row, "caption")
            if not HASH.fullmatch(image_sha):
                raise ValueError("image_sha256 must be 64 lowercase hex characters")
            seed = row.get("generation_seed")
            if not isinstance(seed, int) or isinstance(seed, bool):
                raise ValueError("generation_seed must be an integer")
            culture = row.get("target_culture")
            if culture is not None and (not isinstance(culture, str) or not culture.strip()):
                raise ValueError("target_culture must be null or a non-empty string")
            culture = culture.strip() if isinstance(culture, str) else None
            key = (system, image_id, culture, seed)
            if key in seen:
                raise ValueError(f"duplicate system/image/culture/seed: {key}")
            seen.add(key)
            metadata = (image_path, image_sha, split)
            if image_id in image_metadata and image_metadata[image_id] != metadata:
                raise ValueError(f"inconsistent image metadata for {image_id}")
            image_metadata[image_id] = metadata
            if check_images and not Path(image_path).is_file():
                raise ValueError(f"image does not exist: {image_path}")
            if caption == "[EMPTY OUTPUT]":
                pass
            elif len(caption) > 1000:
                raise ValueError("caption exceeds 1000 characters")
            systems.add(system); images.add(image_id); splits.add(split)
            if culture: cultures.add(culture)
            per_system_image[(system, image_id, culture)] += 1
        except Exception as exc:
            errors.append(f"row {index}: {exc}")
    if errors:
        raise ValueError("invalid generations:\n" + "\n".join(errors[:50]))
    return {
        "rows": len(rows), "systems": sorted(systems), "images": len(images),
        "splits": sorted(splits), "target_cultures": sorted(cultures),
        "candidates_per_system_image": {
            f"{system}/{image}/{culture or '-'}": count
            for (system, image, culture), count in sorted(
                per_system_image.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
            )
        },
    }


def validate_rating_payload(
    payload: dict[str, Any], mapping_by_id: dict[str, dict[str, Any]], *, strict_complete: bool = True
) -> list[str]:
    errors = []
    rater_id = payload.get("rater_id")
    if not isinstance(rater_id, str) or not rater_id.strip():
        errors.append("missing rater_id")
    metadata = payload.get("judge_metadata")
    required_meta = {"provider", "model", "version_or_date", "temperature", "prompt_sha256"}
    if not isinstance(metadata, dict) or not required_meta.issubset(metadata):
        errors.append("judge_metadata is missing required fields")
    else:
        if not HASH.fullmatch(str(metadata["prompt_sha256"])):
            errors.append("judge_metadata.prompt_sha256 is not SHA-256")
        if any(not str(metadata[name]).strip() for name in ("provider", "model", "version_or_date")):
            errors.append("judge_metadata provider/model/version_or_date must be non-empty")
        if metadata.get("temperature") != 0:
            errors.append("judge_metadata.temperature must be 0 for the deterministic protocol")
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        return errors + ["decisions must be an object keyed by blind_id"]
    if strict_complete and set(decisions) != set(mapping_by_id):
        errors.append(
            f"decision coverage mismatch: missing={len(set(mapping_by_id)-set(decisions))}, "
            f"extra={len(set(decisions)-set(mapping_by_id))}"
        )
    for blind_id, decision in decisions.items():
        if blind_id not in mapping_by_id:
            errors.append(f"unknown blind_id: {blind_id}")
            continue
        if not isinstance(decision, dict):
            errors.append(f"{blind_id}: decision must be an object")
            continue
        if not isinstance(decision.get("evidence"), str) or not decision["evidence"].strip():
            errors.append(f"{blind_id}: evidence must be one non-empty visual sentence")
        size = int(mapping_by_id[blind_id]["group_size"])
        for metric in ("overall", "best_pick"):
            if decision.get(metric) not in RELATIVE_CHOICES:
                errors.append(f"{blind_id}: invalid {metric}")
        for side in ("A", "B"):
            if decision.get(f"absolute_{side}") not in ABSOLUTE_LABELS:
                errors.append(f"{blind_id}: invalid absolute_{side}")
            best = decision.get(f"best_{side}_index")
            if not isinstance(best, int) or isinstance(best, bool) or not 1 <= best <= size:
                errors.append(f"{blind_id}: invalid best_{side}_index")
            labels = decision.get(f"candidate_labels_{side}")
            if not isinstance(labels, list) or len(labels) != size or any(
                label not in ABSOLUTE_LABELS for label in labels
            ):
                errors.append(f"{blind_id}: invalid candidate_labels_{side}")
            dimensions = decision.get(f"dimensions_{side}")
            if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
                errors.append(f"{blind_id}: dimensions_{side} must contain exactly {DIMENSIONS}")
            else:
                for name in CORE_DIMENSIONS:
                    value = dimensions[name]
                    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
                        errors.append(f"{blind_id}: {name}_{side} must be integer 1..5")
                for name in OPTIONAL_DIMENSIONS:
                    value = dimensions[name]
                    if value is not None and (
                        not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5
                    ):
                        errors.append(f"{blind_id}: {name}_{side} must be null or integer 1..5")
    return errors


def index_generations(
    rows: Iterable[dict[str, Any]],
) -> dict[tuple[str, str, str | None], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        culture = row.get("target_culture")
        culture = culture.strip() if isinstance(culture, str) else None
        grouped[(row["system_id"], row["image_id"], culture)].append(row)
    return grouped
