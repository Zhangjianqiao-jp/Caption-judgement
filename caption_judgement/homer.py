"""HOMER-compatible unbiased Pass@K aggregation.

HOMER treats a candidate as successful when it is accepted by the evaluator's
reference-group criterion.  This module consumes one row per image/system/trial
with the number of successful candidates and applies the unbiased estimator
reported in the paper:

    Pass@k = 1 - C(n-c, k) / C(n, k)

It does not decide whether a caption is funny; the evaluator or a deterministic
reference matcher must provide ``winning_caption_count``.
"""
from __future__ import annotations

from collections import defaultdict
import math
import random
from typing import Any, Iterable

from .provenance import provenance_sha256


def unbiased_pass_at_k(candidate_count: int, winning_caption_count: int, k: int) -> float:
    """Return the unbiased estimator, with explicit edge-case handling."""
    n = candidate_count
    c = winning_caption_count
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("candidate_count must be a positive integer")
    if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= n:
        raise ValueError("winning_caption_count must be an integer in [0, candidate_count]")
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= n:
        raise ValueError("k must satisfy 1 <= k <= candidate_count")
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    values = sorted(values)
    index = int(round((len(values) - 1) * probability))
    return values[index]


def _bootstrap(values_by_image: dict[str, float], *, seed: int, replicates: int) -> tuple[float, float]:
    if not values_by_image:
        raise ValueError("no image observations")
    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    rng = random.Random(seed)
    values = list(values_by_image.values())
    draws = []
    for _ in range(replicates):
        draws.append(sum(rng.choice(values) for _ in values) / len(values))
    return _percentile(draws, 0.025), _percentile(draws, 0.975)


def summarize_homer_pass_at_k(
    records: Iterable[dict[str, Any]], *, ks: tuple[int, ...] = (1, 3, 5),
    bootstrap_seed: int = 20250308, bootstrap_replicates: int = 10_000,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = list(records)
    if not rows:
        raise ValueError("HOMER records are empty")
    if not ks or len(set(ks)) != len(ks) or any(not isinstance(k, int) or k < 1 for k in ks):
        raise ValueError("ks must contain unique positive integers")
    seen: set[tuple[str, str, int, str]] = set()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    candidate_counts: set[int] = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"row {index} must be an object")
        for field in ("system_id", "image_id"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"row {index}: {field} must be non-empty")
        trial = row.get("trial")
        if not isinstance(trial, int) or isinstance(trial, bool) or trial < 0:
            raise ValueError(f"row {index}: trial must be a non-negative integer")
        n = row.get("candidate_count")
        c = row.get("winning_caption_count")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError(f"row {index}: candidate_count must be positive integer")
        if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c <= n:
            raise ValueError(f"row {index}: winning_caption_count out of range")
        group = row.get("reference_group", "all")
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"row {index}: reference_group must be non-empty")
        key = (row["system_id"], row["image_id"], trial, group)
        if key in seen:
            raise ValueError(f"duplicate system/image/trial/group: {key}")
        seen.add(key)
        candidate_counts.add(n)
        grouped[(row["system_id"], group)].append(row)
    if len(candidate_counts) != 1:
        raise ValueError("candidate_count must be constant within one HOMER evaluation")
    candidate_count = next(iter(candidate_counts))
    if any(k > candidate_count for k in ks):
        raise ValueError("requested k exceeds candidate_count")
    if provenance is not None:
        track = provenance.get("track")
        generation = provenance.get("generation", {})
        if track == "homer_comparable":
            if candidate_count != 5:
                raise ValueError("HOMER-comparable track requires five candidates per image")
            trials = generation.get("repeated_trials")
            if trials != 5:
                raise ValueError("HOMER-comparable track requires five repeated trials")

    summaries = []
    for (system, reference_group), group_rows in sorted(grouped.items()):
        image_trial_values: dict[tuple[str, int], dict[int, float]] = defaultdict(dict)
        for row in group_rows:
            image_trial_values[(row["image_id"], row["trial"])] = {
                k: unbiased_pass_at_k(candidate_count, row["winning_caption_count"], k) for k in ks
            }
        image_ids = sorted({image for image, _ in image_trial_values})
        trials = sorted({trial for _, trial in image_trial_values})
        if any((image, trial) not in image_trial_values for image in image_ids for trial in trials):
            raise ValueError(f"incomplete image x trial grid for {system}/{reference_group}")
        for k in ks:
            by_image = {
                image: sum(image_trial_values[(image, trial)][k] for trial in trials) / len(trials)
                for image in image_ids
            }
            lo, hi = _bootstrap(
                by_image, seed=bootstrap_seed + len(summaries) * 101 + k,
                replicates=bootstrap_replicates,
            )
            by_trial = {
                str(trial): sum(image_trial_values[(image, trial)][k] for image in image_ids) / len(image_ids)
                for trial in trials
            }
            summaries.append({
                "system_id": system,
                "reference_group": reference_group,
                "k": k,
                "candidate_count": candidate_count,
                "images": len(image_ids),
                "repeated_trials": len(trials),
                "pass_at_k": sum(by_image.values()) / len(by_image),
                "ci95_low": lo,
                "ci95_high": hi,
                "per_trial": by_trial,
            })
    result: dict[str, Any] = {
        "schema_version": 1,
        "protocol": "homer_unbiased_pass_at_k",
        "statistical_unit": "image_id",
        "formula": "1 - C(n-c,k) / C(n,k)",
        "candidate_count": candidate_count,
        "k_values": list(ks),
        "bootstrap": {"seed": bootstrap_seed, "replicates": bootstrap_replicates, "hierarchy": "image"},
        "summaries": summaries,
    }
    if provenance is not None:
        result["provenance"] = provenance
        result["provenance_sha256"] = provenance_sha256(provenance)
    return result
