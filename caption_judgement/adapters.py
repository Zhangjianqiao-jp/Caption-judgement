from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .io import sha256_file


def adapt_humor_generator_v35(
    rows: Iterable[dict[str, Any]], *, verify_images: bool = True,
) -> list[dict[str, Any]]:
    """Convert Humor-generator/v3.5 formal generations without losing receiver identity."""
    output = []
    hash_cache: dict[str, str] = {}
    required = {"receiver", "condition", "cluster_id", "image", "caption", "generation_seed"}
    for index, source in enumerate(rows, 1):
        missing = required - set(source)
        if missing:
            raise ValueError(f"v3.5 row {index} missing {sorted(missing)}")
        image = str(source["image"])
        if image not in hash_cache:
            path = Path(image)
            if verify_images and not path.is_file():
                raise ValueError(f"v3.5 row {index} image does not exist: {image}")
            hash_cache[image] = sha256_file(path) if path.is_file() else str(source.get("image_sha256") or "")
        if len(hash_cache[image]) != 64:
            raise ValueError(f"v3.5 row {index} requires an existing image or image_sha256")
        output.append({
            "schema_version": 1,
            "system_id": f"{source['receiver']}::{source['condition']}",
            "receiver": str(source["receiver"]),
            "condition": str(source["condition"]),
            "image_id": str(source["cluster_id"]),
            "image_path": image,
            "image_sha256": hash_cache[image],
            "split": str(source.get("split") or "unspecified"),
            "target_culture": source.get("target_culture"),
            "caption": str(source["caption"]),
            "generation_seed": int(source["generation_seed"]),
            "source_row_id": source.get("row_id"),
            "generation_config_sha256": source.get("generation_config_sha256"),
            "checkpoint_manifest_sha256": source.get("checkpoint_manifest_sha256"),
        })
    return output


def adapt_auto(rows: Iterable[dict[str, Any]], *, verify_images: bool = True) -> list[dict[str, Any]]:
    rows = list(rows)
    if not rows:
        raise ValueError("input is empty")
    if {"receiver", "condition", "cluster_id", "image"}.issubset(rows[0]):
        return adapt_humor_generator_v35(rows, verify_images=verify_images)
    return [dict(row) for row in rows]
