from __future__ import annotations

from .contracts import DIMENSIONS
from .io import canonical_json, sha256_bytes


RUBRIC_VERSION = "humor-caption-v1.1"

SYSTEM_PROMPT = """You are an impartial evaluator of humorous captions for a visible image.
Do not infer which model produced either group. Inspect the image before judging text.

Evaluation order (follow exactly):
1. Describe privately the visible situation and verify each caption's factual grounding.
2. Score each group independently. Do not compare A with B yet.
3. Identify the best caption in each group.
4. Compare the two groups for Overall quality and compare their best captions for Best Pick.
5. Return only the requested JSON. Do not reveal private reasoning.

Core criteria, all equally visible in the output:
- humor: setup/payoff, incongruity, surprise, wit; not merely a factual description;
- image_grounding: the joke depends on visible details and avoids invented objects/actions;
- image_relevance: the caption specifically answers this image rather than a broadly reusable scene;
- originality: avoids stock meme phrases, clichés, and generic jokes reusable on unrelated images;
- specificity: exploits a precise relation, conflict, role reversal, or visual implication;
- fluency: concise, natural caption writing.
hallucination_severity is 1=no unsupported content and 5=the joke depends on major invented content.
If target_culture is present, cultural_fit measures comprehensibility and appropriateness for that
audience. stereotype_risk is 1=safe and 5=high risk; use null for both when no target culture exists.

Absolute labels:
- good: genuinely funny, image-grounded, publishable with at most minor editing;
- weak: understandable and relevant, but only mildly funny, generic, predictable, or awkward;
- bad: not funny, materially ungrounded, incoherent, copied/near-duplicate, or unsafe.

Relative labels: A, B, or Tie. Use Tie when the difference is not meaningful. Ignore group order,
caption order, verbosity, punctuation, emojis, and perceived model identity except when they affect
the stated criteria. A polished generic joke must not beat an image-specific joke merely for style.

Operational safeguards (mandatory):
- The operator must attach the actual image referenced by image_path as an image input. A path
  written as text is not visual evidence; if the image is not visible, do not guess or complete the
  packet.
- Evaluate exactly one packet per request. Do not use decisions, hidden mappings, or context from
  any other packet, and do not share your decision with another evaluator.
- The inference/API temperature must be exactly 0. If the runtime cannot enforce temperature=0,
  the operator must stop rather than silently use a different setting.
- Never receive, request, infer, or expose private_mapping.jsonl, blind.secret, system identities,
  checkpoint names, or training methods. They are restricted to the trusted aggregation machine.
- Return only the decision JSON for this blind_id. The trusted orchestrator, not the model, writes
  the decision into the assigned rater file (judge-1.json, judge-2.json, or judge-3.json).
- Do not add prose, Markdown, chain-of-thought, or fields outside the requested schema.
"""


def prompt_sha256() -> str:
    return sha256_bytes(SYSTEM_PROMPT.encode("utf-8"))


def render_judge_prompt(packet: dict) -> str:
    size = len(packet["group_A"])
    dimensions = {name: "integer 1..5" for name in DIMENSIONS}
    dimensions["cultural_fit"] = "null or integer 1..5"
    dimensions["stereotype_risk"] = "null or integer 1..5"
    skeleton = {
        "overall": "A|B|Tie",
        "best_pick": "A|B|Tie",
        "best_A_index": f"integer 1..{size}",
        "best_B_index": f"integer 1..{size}",
        "absolute_A": "good|weak|bad",
        "absolute_B": "good|weak|bad",
        "candidate_labels_A": ["good|weak|bad"] * size,
        "candidate_labels_B": ["good|weak|bad"] * size,
        "dimensions_A": dimensions,
        "dimensions_B": dimensions,
        "evidence": "one concise sentence grounded in the visible image",
    }
    task = {
        "blind_id": packet["blind_id"],
        "image_path": packet["image_path"],
        "target_culture": packet.get("target_culture"),
        "group_A": packet["group_A"],
        "group_B": packet["group_B"],
    }
    return SYSTEM_PROMPT + "\nTASK:\n" + canonical_json(task) + "\nOUTPUT JSON:\n" + canonical_json(skeleton)
