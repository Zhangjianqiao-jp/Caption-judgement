from __future__ import annotations

import itertools
import math
import random
from typing import Iterable


def mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def image_clustered_bootstrap(
    values_by_image: dict[str, list[float]], *, seed: int = 20250308,
    replicates: int = 10_000, confidence: float = 0.95,
) -> tuple[float, float]:
    """Resample images, then raters within each sampled image."""
    images = sorted(values_by_image)
    if not images:
        raise ValueError("bootstrap requires at least one image unit")
    rng = random.Random(seed)
    draws = []
    for _ in range(replicates):
        sampled = [rng.choice(images) for _ in images]
        per_image = [
            sum(rng.choice(values_by_image[image]) for _ in values_by_image[image])
            / len(values_by_image[image])
            for image in sampled
        ]
        draws.append(sum(per_image) / len(per_image))
    draws.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = draws[max(0, int(alpha * replicates))]
    hi = draws[min(replicates - 1, int((1.0 - alpha) * replicates) - 1)]
    return lo, hi


def paired_sign_flip_test(
    image_effects: Iterable[float], *, seed: int = 20250308,
    simulations: int = 100_000,
) -> float:
    """Two-sided paired randomization test of mean effect=0."""
    effects = [float(value) for value in image_effects]
    if not effects:
        raise ValueError("sign-flip test requires effects")
    observed = abs(sum(effects) / len(effects))
    extreme = 0
    total = 0
    exact = len(effects) <= 20
    if exact:
        signs = itertools.product((-1.0, 1.0), repeat=len(effects))
    else:
        rng = random.Random(seed)
        signs = ((1.0 if rng.random() < 0.5 else -1.0 for _ in effects) for _ in range(simulations))
    for sign_row in signs:
        statistic = abs(sum(sign * effect for sign, effect in zip(sign_row, effects)) / len(effects))
        extreme += statistic >= observed - 1e-15
        total += 1
    return extreme / total if exact else (extreme + 1) / (total + 1)


def holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        value = min(1.0, (count - rank) * p_values[index])
        running = max(running, value)
        adjusted[index] = running
    return adjusted


def krippendorff_alpha_nominal(items: dict[str, list[str]]) -> float | None:
    """Nominal alpha for variable raters per item; missing ratings are omitted."""
    usable = [labels for labels in items.values() if len(labels) >= 2]
    if not usable:
        return None
    disagreement = total_pairs = 0.0
    counts: dict[str, int] = {}
    total = 0
    for labels in usable:
        n = len(labels)
        total_pairs += n * (n - 1)
        disagreement += sum(a != b for i, a in enumerate(labels) for j, b in enumerate(labels) if i != j)
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
            total += 1
    observed = disagreement / total_pairs
    if total < 2:
        return None
    expected = 1.0 - sum(count * (count - 1) for count in counts.values()) / (total * (total - 1))
    if math.isclose(expected, 0.0):
        return 1.0 if math.isclose(observed, 0.0) else None
    return 1.0 - observed / expected
