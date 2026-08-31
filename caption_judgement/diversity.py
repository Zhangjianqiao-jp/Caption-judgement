from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any, Iterable


TOKEN = re.compile(r"\b[\w']+\b", re.UNICODE)
OFFICIAL_EAD_VOCAB_SIZE = 32_000


def _tokens(text: str) -> list[str]: return TOKEN.findall(text.casefold())


def _distinct(captions: list[str], n: int) -> float:
    grams = [tuple(tokens[i:i+n]) for caption in captions for tokens in [_tokens(caption)] for i in range(len(tokens)-n+1)]
    return len(set(grams)) / len(grams) if grams else 0.0


def official_ead(captions: list[str], vocabulary_size: int = OFFICIAL_EAD_VOCAB_SIZE) -> float:
    scores = []
    for n in range(1, 6):
        grams = []
        for caption in captions:
            words = [part for part in caption.replace(".", "").replace("\n", "").split(" ") if part]
            grams.extend(tuple(words[i:i+n]) for i in range(len(words)-n+1))
        denominator = vocabulary_size * (1 - ((vocabulary_size - 1) / vocabulary_size) ** len(grams))
        scores.append(len(set(grams)) / denominator if denominator else 0.0)
    return sum(scores) / len(scores)


def _semantic_metrics(captions: list[str], model: Any | None) -> dict[str, float | None]:
    if model is None or not captions:
        return {"official_sbert_all_mpnet_base_v2_diversity": None, "vendi_score_sbert": None}
    import numpy as np
    embeddings = np.asarray(model.encode(captions, normalize_embeddings=True))
    kernel = embeddings @ embeddings.T
    diversity = float(1.0 - np.mean(kernel))  # Humor in AI includes the diagonal.
    eigen = np.clip(np.linalg.eigvalsh((kernel + kernel.T) * 0.5), 0.0, None)
    probabilities = eigen / max(float(eigen.sum()), 1e-12)
    probabilities = probabilities[probabilities > 1e-12]
    vendi = float(math.exp(-float(np.sum(probabilities * np.log(probabilities)))))
    return {"official_sbert_all_mpnet_base_v2_diversity": diversity, "vendi_score_sbert": vendi}


def candidate_metrics(captions: list[str], sbert_model: Any | None = None) -> dict[str, float | int | None]:
    captions = [" ".join(value.split()) for value in captions if value.strip()]
    token_sets = [set(_tokens(value)) for value in captions]
    distances = []
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            union = token_sets[i] | token_sets[j]
            distances.append(1 - len(token_sets[i] & token_sets[j]) / len(union) if union else 0.0)
    return {"candidates": len(captions), "unique_caption_rate": len(set(map(str.casefold, captions))) / len(captions) if captions else 0.0,
            "distinct_1": _distinct(captions, 1), "distinct_2": _distinct(captions, 2),
            "mean_pairwise_token_jaccard_distance": sum(distances) / len(distances) if distances else 0.0,
            "official_average_ead_n1_n5": official_ead(captions), **_semantic_metrics(captions, sbert_model)}


def summarize_diversity(rows: Iterable[dict[str, Any]], min_candidates: int = 2,
                        sbert_model: Any | None = None) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str | None], list[str]] = defaultdict(list)
    for row in rows: grouped[(row["system_id"], row["image_id"], row.get("target_culture"))].append(row["caption"])
    per_unit = []
    for (system, image, culture), captions in sorted(grouped.items(), key=str):
        if len(captions) < min_candidates: raise ValueError(f"{system}/{image}/{culture} has fewer than {min_candidates} candidates")
        per_unit.append({"system": system, "image_id": image, "target_culture": culture,
                         **candidate_metrics(captions, sbert_model)})
    summaries = []
    for system in sorted({row["system"] for row in per_unit}):
        values = [row for row in per_unit if row["system"] == system]
        names = ("unique_caption_rate", "distinct_1", "distinct_2", "mean_pairwise_token_jaccard_distance", "official_average_ead_n1_n5",
                 "official_sbert_all_mpnet_base_v2_diversity", "vendi_score_sbert")
        means = {}
        for name in names:
            present = [float(v[name]) for v in values if v[name] is not None]
            means[f"mean_{name}"] = sum(present) / len(present) if present else None
        summaries.append({"system": system, "image_units": len(values), **means})
    return {"schema_version": 1, "statistical_unit": "image_id x target_culture", "per_unit": per_unit, "system_summary": summaries,
            "note": "EAD and optional all-mpnet-base-v2 follow Humor in AI; diversity must be interpreted with absolute quality."}
