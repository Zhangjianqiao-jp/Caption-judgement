"""Strict, non-secret experiment provenance for caption evaluation.

The public blind packets intentionally contain no model identity.  Provenance is
kept in the private manifest and the post-aggregation report so that a result
can be audited without allowing a judge to infer which side is the new model.
"""
from __future__ import annotations

import re
from typing import Any

from .io import canonical_json, sha256_bytes


HASH = re.compile(r"^[0-9a-f]{64}$")


def _required_string(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")


def _hash(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        errors.append(f"{field} must be a lowercase SHA-256 hex string")


def validate_provenance(provenance: Any) -> list[str]:
    """Return validation errors for a run provenance object.

    The validator is deliberately fail-closed for fields that affect the
    interpretation of a claim, while allowing optional checkpoint/config
    hashes for older generation adapters.
    """
    errors: list[str] = []
    if not isinstance(provenance, dict):
        return ["provenance must be an object"]
    for field in ("schema_version", "evaluation_id", "track", "protocol", "dataset", "code_commit"):
        if field == "schema_version":
            if provenance.get(field) != 1:
                errors.append("provenance.schema_version must be 1")
        else:
            _required_string(provenance.get(field), f"provenance.{field}", errors)
    _hash(provenance.get("source_generations_sha256"), "provenance.source_generations_sha256", errors)
    _hash(provenance.get("dataset_manifest_sha256"), "provenance.dataset_manifest_sha256", errors)

    models = provenance.get("models")
    if not isinstance(models, list) or not models:
        errors.append("provenance.models must be a non-empty list")
    else:
        roles: set[str] = set()
        for index, model in enumerate(models):
            prefix = f"provenance.models[{index}]"
            if not isinstance(model, dict):
                errors.append(f"{prefix} must be an object")
                continue
            for field in ("role", "model_id", "revision_or_snapshot"):
                _required_string(model.get(field), f"{prefix}.{field}", errors)
            role = model.get("role")
            if isinstance(role, str):
                if role in roles:
                    errors.append(f"duplicate model role: {role}")
                roles.add(role)
            adapter = model.get("adapter")
            if adapter is not None and not isinstance(adapter, str):
                errors.append(f"{prefix}.adapter must be null or a string")
            _hash(model.get("prompt_sha256"), f"{prefix}.prompt_sha256", errors)
            for optional in ("checkpoint_manifest_sha256", "config_sha256"):
                if model.get(optional) is not None:
                    _hash(model.get(optional), f"{prefix}.{optional}", errors)

    generation = provenance.get("generation")
    if not isinstance(generation, dict):
        errors.append("provenance.generation must be an object")
    else:
        temperature = generation.get("temperature")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or temperature < 0:
            errors.append("provenance.generation.temperature must be a non-negative number")
        candidates = generation.get("candidates_per_image")
        if not isinstance(candidates, int) or isinstance(candidates, bool) or candidates < 1:
            errors.append("provenance.generation.candidates_per_image must be a positive integer")
        seeds = generation.get("seeds")
        if not isinstance(seeds, list) or len(seeds) < 1 or any(
            not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds
        ) or len(set(seeds)) != len(seeds):
            errors.append("provenance.generation.seeds must be a list of unique integers")
        trials = generation.get("repeated_trials")
        if trials is not None and (not isinstance(trials, int) or isinstance(trials, bool) or trials < 1):
            errors.append("provenance.generation.repeated_trials must be a positive integer")

    evaluator = provenance.get("evaluator")
    if not isinstance(evaluator, dict):
        errors.append("provenance.evaluator must be an object")
    else:
        for field in ("model_id", "canonical_model_id", "version_or_date"):
            _required_string(evaluator.get(field), f"provenance.evaluator.{field}", errors)
        _hash(evaluator.get("prompt_sha256"), "provenance.evaluator.prompt_sha256", errors)
        if evaluator.get("temperature") != 0:
            errors.append("provenance.evaluator.temperature must be exactly 0")
        substitution = evaluator.get("substitution")
        if not isinstance(substitution, bool):
            errors.append("provenance.evaluator.substitution must be boolean")
        else:
            actual = evaluator.get("model_id")
            canonical = evaluator.get("canonical_model_id")
            if substitution != (actual != canonical):
                errors.append("provenance.evaluator.substitution must match model_id != canonical_model_id")
            if substitution and evaluator.get("substitution_label") != "HOMER-protocol adapted evaluation":
                errors.append("evaluator substitution requires the exact adapted-evaluation label")
    protocol = provenance.get("protocol_details")
    if protocol is not None and not isinstance(protocol, dict):
        errors.append("provenance.protocol_details must be an object when provided")
    return errors


def provenance_sha256(provenance: dict[str, Any]) -> str:
    errors = validate_provenance(provenance)
    if errors:
        raise ValueError("invalid provenance:\n" + "\n".join(errors))
    return sha256_bytes(canonical_json(provenance).encode("utf-8"))


def validate_rating_provenance(
    provenance: dict[str, Any], rating_metadata: dict[str, Any]
) -> list[str]:
    """Check that a judge response identifies the evaluator declared in a run."""
    errors = []
    evaluator = provenance["evaluator"]
    if rating_metadata.get("model") != evaluator["model_id"]:
        errors.append("rating judge_metadata.model does not match provenance evaluator.model_id")
    if rating_metadata.get("temperature") != evaluator["temperature"]:
        errors.append("rating judge_metadata.temperature does not match provenance evaluator.temperature")
    if rating_metadata.get("prompt_sha256") != evaluator["prompt_sha256"]:
        errors.append("rating prompt SHA-256 does not match provenance evaluator prompt")
    return errors
