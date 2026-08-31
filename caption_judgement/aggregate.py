from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .contracts import ABSOLUTE_VALUE, DIMENSIONS, validate_rating_payload
from .statistics import (
    holm_adjust, image_clustered_bootstrap, krippendorff_alpha_nominal,
    mean, paired_sign_flip_test,
)
from .prompts import prompt_sha256


def _unit(row: dict[str, Any]) -> str:
    return f"{row['image_id']}::{row.get('target_culture') or '-'}"


def _system_value(choice: str, mapping: dict[str, Any]) -> float:
    if choice == "Tie":
        return 0.5
    selected = mapping[f"condition_{choice}"]
    return 1.0 if selected == mapping["challenger"] else 0.0


def _system_label(value: float) -> str:
    return "challenger" if value > 0.5 else "reference" if value < 0.5 else "tie"


def aggregate_ratings(
    mapping_rows: Iterable[dict[str, Any]], rating_payloads: Iterable[dict[str, Any]], *,
    bootstrap_seed: int = 20250308, bootstrap_replicates: int = 10_000,
) -> dict[str, Any]:
    mapping_rows = list(mapping_rows)
    mapping = {row["blind_id"]: row for row in mapping_rows}
    if len(mapping) != len(mapping_rows):
        raise ValueError("duplicate blind_id in private mapping")
    payloads = list(rating_payloads)
    if not payloads:
        raise ValueError("no rating payloads")
    rater_ids = [str(payload.get("rater_id")) for payload in payloads]
    if len(set(rater_ids)) != len(rater_ids):
        raise ValueError("duplicate rater_id")
    for payload in payloads:
        errors = validate_rating_payload(payload, mapping, strict_complete=True)
        if errors:
            raise ValueError("invalid rating payload:\n" + "\n".join(errors[:50]))
        if payload["judge_metadata"]["prompt_sha256"] != prompt_sha256():
            raise ValueError("rating payload was produced with a different rubric prompt SHA-256")

    # Raw records keep orientations for position-bias diagnostics.
    relative: dict[tuple, list[tuple[int, float, str]]] = defaultdict(list)
    absolute: dict[tuple, list[tuple[int, float, str]]] = defaultdict(list)
    dimensions: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    a_choices = Counter()
    for payload in payloads:
        rater = payload["rater_id"]
        for blind_id, decision in payload["decisions"].items():
            row = mapping[blind_id]
            base = (row["comparison_family"], row["reference"], row["challenger"], _unit(row), rater, row["mirror_pair_id"])
            for metric in ("overall", "best_pick"):
                choice = decision[metric]
                relative[base + (metric,)].append((row["orientation"], _system_value(choice, row), choice))
                a_choices[(metric, choice)] += 1
            for side in ("A", "B"):
                system = row[f"condition_{side}"]
                absolute[(row["comparison_family"], system, _unit(row), rater, row["mirror_pair_id"], "group")].append(
                    (row["orientation"], ABSOLUTE_VALUE[decision[f"absolute_{side}"]], decision[f"absolute_{side}"])
                )
                for index, label in enumerate(decision[f"candidate_labels_{side}"]):
                    seed = row[f"seeds_{side}"][index]
                    absolute[(row["comparison_family"], system, _unit(row), rater, row["mirror_pair_id"], f"seed:{seed}")].append(
                        (row["orientation"], ABSOLUTE_VALUE[label], label)
                    )
                for name in DIMENSIONS:
                    value = decision[f"dimensions_{side}"][name]
                    if value is not None:
                        dimensions[(row["comparison_family"], system, _unit(row), rater, row["mirror_pair_id"], name)].append(
                            (row["orientation"], float(value))
                        )

    collapsed_relative = []
    mirror_consistency = []
    for key, observations in relative.items():
        family, reference, challenger, unit, rater, pair_id, metric = key
        values = [value for _, value, _ in observations]
        value = sum(values) / len(values)
        if len(observations) == 2:
            mirror_consistency.append(values[0] == values[1])
        collapsed_relative.append({
            "family": family, "reference": reference, "challenger": challenger,
            "unit": unit, "rater": rater, "pair_id": pair_id, "metric": metric,
            "value": value, "label": _system_label(value), "orientations": len(observations),
        })

    relative_summaries = []
    comparison_keys = sorted({(r["family"], r["reference"], r["challenger"], r["metric"]) for r in collapsed_relative})
    for offset, key in enumerate(comparison_keys):
        rows = [row for row in collapsed_relative if (row["family"], row["reference"], row["challenger"], row["metric"]) == key]
        by_image: dict[str, list[float]] = defaultdict(list)
        agreement: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            by_image[row["unit"]].append(row["value"])
            agreement[row["unit"]].append(row["label"])
        image_means = {unit: sum(values) / len(values) for unit, values in by_image.items()}
        estimate = sum(image_means.values()) / len(image_means)
        lo, hi = image_clustered_bootstrap(
            by_image, seed=bootstrap_seed + offset, replicates=bootstrap_replicates,
        )
        p_value = paired_sign_flip_test(
            [value - 0.5 for value in image_means.values()], seed=bootstrap_seed + offset,
        )
        relative_summaries.append({
            "family": key[0], "reference": key[1], "challenger": key[2], "metric": key[3],
            "challenger_win_rate_ties_half": estimate, "ci95_low": lo, "ci95_high": hi,
            "images": len(by_image), "ratings_after_mirror_collapse": len(rows),
            "p_value_sign_flip": p_value,
            "krippendorff_alpha_nominal": krippendorff_alpha_nominal(agreement),
        })
    adjusted = holm_adjust([row["p_value_sign_flip"] for row in relative_summaries])
    for row, value in zip(relative_summaries, adjusted):
        row["p_value_holm"] = value

    collapsed_absolute = []
    for key, observations in absolute.items():
        family, system, unit, rater, pair_id, scope = key
        values = [value for _, value, _ in observations]
        labels = [label for _, _, label in observations]
        collapsed_absolute.append({
            "family": family, "system": system, "unit": unit, "rater": rater,
            "scope": scope, "score": sum(values) / len(values),
            "label": labels[0] if len(set(labels)) == 1 else "mirror_disagreement",
        })
    absolute_summaries = []
    for family, system, scope in sorted({(r["family"], r["system"], r["scope"]) for r in collapsed_absolute}):
        rows = [r for r in collapsed_absolute if (r["family"], r["system"], r["scope"]) == (family, system, scope)]
        by_image: dict[str, list[float]] = defaultdict(list)
        labels = Counter()
        for row in rows:
            by_image[row["unit"]].append(row["score"]); labels[row["label"]] += 1
        estimate = mean(mean(values) for values in by_image.values())
        lo, hi = image_clustered_bootstrap(by_image, seed=bootstrap_seed, replicates=bootstrap_replicates)
        absolute_summaries.append({
            "family": family, "system": system, "scope": scope, "absolute_score": estimate,
            "ci95_low": lo, "ci95_high": hi, "images": len(by_image), "label_counts": dict(labels),
        })
    # A system-level candidate endpoint pools seeds only after retaining image as the cluster.
    for family, system in sorted({(r["family"], r["system"]) for r in collapsed_absolute}):
        rows = [r for r in collapsed_absolute if r["family"] == family and r["system"] == system and r["scope"].startswith("seed:")]
        by_image: dict[str, list[float]] = defaultdict(list); labels = Counter()
        for row in rows:
            by_image[row["unit"]].append(row["score"]); labels[row["label"]] += 1
        if by_image:
            lo, hi = image_clustered_bootstrap(by_image, seed=bootstrap_seed, replicates=bootstrap_replicates)
            absolute_summaries.append({"family": family, "system": system, "scope": "candidate:any",
                "absolute_score": mean(mean(values) for values in by_image.values()),
                "ci95_low": lo, "ci95_high": hi, "images": len(by_image), "label_counts": dict(labels)})

    collapsed_dimensions = []
    for key, observations in dimensions.items():
        family, system, unit, rater, pair_id, name = key
        collapsed_dimensions.append({
            "family": family, "system": system, "unit": unit, "rater": rater,
            "dimension": name, "score": mean(value for _, value in observations),
        })
    dimension_summaries = []
    for family, system, name in sorted({(r["family"], r["system"], r["dimension"]) for r in collapsed_dimensions}):
        rows = [r for r in collapsed_dimensions if (r["family"], r["system"], r["dimension"]) == (family, system, name)]
        by_image: dict[str, list[float]] = defaultdict(list)
        for row in rows: by_image[row["unit"]].append(float(row["score"]))
        lo, hi = image_clustered_bootstrap(by_image, seed=bootstrap_seed, replicates=bootstrap_replicates)
        dimension_summaries.append({
            "family": family, "system": system, "dimension": name,
            "mean": mean(mean(v) for v in by_image.values()), "ci95_low": lo, "ci95_high": hi,
            "images": len(by_image),
        })

    seed_variance = []
    for family, system in sorted({(r["family"], r["system"]) for r in collapsed_absolute}):
        rows = [r for r in collapsed_absolute if r["family"] == family and r["system"] == system and r["scope"].startswith("seed:")]
        by_seed: dict[str, list[float]] = defaultdict(list)
        for row in rows: by_seed[row["scope"].split(":", 1)[1]].append(row["score"])
        seed_means = {seed: mean(values) for seed, values in sorted(by_seed.items())}
        values = list(seed_means.values())
        variance = (sum((value - sum(values)/len(values))**2 for value in values)/(len(values)-1)) if len(values) > 1 else None
        seed_variance.append({"family": family, "system": system,
                              "per_generation_seed_absolute_score": seed_means,
                              "generation_seed_sample_variance": variance})

    total_relative = sum(a_choices[(metric, choice)] for metric in ("overall", "best_pick") for choice in ("A", "B", "Tie"))
    return {
        "schema_version": 1,
        "statistical_unit": "image_id x target_culture",
        "tie_policy": "Tie contributes 0.5 to challenger win rate",
        "mirror_policy": "collapse within rater x image-unit x comparison before inference",
        "bootstrap": {"seed": bootstrap_seed, "replicates": bootstrap_replicates, "hierarchy": "image then rater"},
        "raters": rater_ids,
        "position_diagnostics": {
            "raw_A_rate_excluding_ties": (
                sum(a_choices[(metric, "A")] for metric in ("overall", "best_pick")) /
                max(1, sum(a_choices[(metric, side)] for metric in ("overall", "best_pick") for side in ("A", "B")))
            ),
            "mirror_system_choice_consistency": mean(float(value) for value in mirror_consistency),
            "mirrored_decision_pairs": len(mirror_consistency), "raw_relative_decisions": total_relative,
        },
        "relative": relative_summaries,
        "absolute": absolute_summaries,
        "dimensions": dimension_summaries,
        "seed_variance": seed_variance,
        "collapsed_relative": collapsed_relative,
    }
