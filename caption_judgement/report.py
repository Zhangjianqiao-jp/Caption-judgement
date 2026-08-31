from __future__ import annotations

from pathlib import Path
from typing import Any


def render_markdown(aggregate: dict[str, Any], audit: dict[str, Any] | None = None,
                    diversity: dict[str, Any] | None = None) -> str:
    lines = ["# Humorous Caption Evaluation Report", "", "## Protocol", "",
             f"- Statistical unit: `{aggregate['statistical_unit']}`",
             f"- Tie policy: {aggregate['tie_policy']}",
             f"- Mirror policy: {aggregate['mirror_policy']}",
             f"- Raters: {', '.join(aggregate['raters'])}", "", "## Relative results", "",
             "| Family | Reference | Challenger | Metric | Win rate | 95% CI | Holm p | Images | α |",
             "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for row in aggregate["relative"]:
        alpha = row["krippendorff_alpha_nominal"]
        alpha_text = f"{alpha:.3f}" if alpha is not None else "NA"
        lines.append(
            f"| {row['family']} | {row['reference']} | {row['challenger']} | {row['metric']} | "
            f"{row['challenger_win_rate_ties_half']:.3f} | [{row['ci95_low']:.3f}, {row['ci95_high']:.3f}] | "
            f"{row['p_value_holm']:.4g} | {row['images']} | {alpha_text} |"
        )
    lines += ["", "## Absolute quality", "",
              "| Family | System | Scope | Score | 95% CI | Images | Labels |",
              "|---|---|---|---:|---:|---:|---|"]
    for row in aggregate["absolute"]:
        if row["scope"] not in {"group", "candidate:any"}:
            continue
        lines.append(f"| {row['family']} | {row['system']} | {row['scope']} | {row['absolute_score']:.3f} | "
                     f"[{row['ci95_low']:.3f}, {row['ci95_high']:.3f}] | {row['images']} | `{row['label_counts']}` |")
    lines += ["", "## Position diagnostics", "",
              f"- Raw A-choice rate excluding ties: {aggregate['position_diagnostics']['raw_A_rate_excluding_ties']:.3f}",
              f"- Mirrored system-choice consistency: {aggregate['position_diagnostics']['mirror_system_choice_consistency']}"]
    if audit:
        lines += ["", "## Input and blinding audit", "", f"```json\n{audit}\n```"]
    if diversity:
        lines += ["", "## Candidate-set diversity", "", "Diversity is reported beside, never in place of, absolute quality.", "",
                  "| System | Image units | Unique | Distinct-1 | Distinct-2 | EAD | SBERT |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for row in diversity["system_summary"]:
            sbert = row.get("mean_official_sbert_all_mpnet_base_v2_diversity")
            sbert_text = f"{sbert:.3f}" if sbert is not None else "NA"
            lines.append(f"| {row['system']} | {row['image_units']} | {row['mean_unique_caption_rate']:.3f} | "
                         f"{row['mean_distinct_1']:.3f} | {row['mean_distinct_2']:.3f} | "
                         f"{row['mean_official_average_ead_n1_n5']:.3f} | {sbert_text} |")
    lines += ["", "## Interpretation rule", "",
              "A system is not declared better from win rate alone. The primary claim additionally requires the preregistered CI rule, acceptable position diagnostics, absolute-quality non-regression, grounding non-regression, and no material generic-template or hallucination increase."]
    return "\n".join(lines) + "\n"


def save_plots(aggregate: dict[str, Any], output_dir: str | Path) -> list[str]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("install caption-judgement[plot] to render plots") from exc
    output = Path(output_dir); output.mkdir(parents=True, exist_ok=True)
    created = []
    rows = aggregate["relative"]
    if rows:
        labels = [f"{r['challenger']} vs {r['reference']} ({r['metric']})" for r in rows]
        values = [r["challenger_win_rate_ties_half"] for r in rows]
        low = [v-r["ci95_low"] for v, r in zip(values, rows)]
        high = [r["ci95_high"]-v for v, r in zip(values, rows)]
        fig, ax = plt.subplots(figsize=(9, max(3, len(rows)*0.45)))
        ax.errorbar(values, range(len(rows)), xerr=[low, high], fmt="o", capsize=4)
        ax.axvline(0.5, color="black", linestyle="--", linewidth=1)
        ax.set_yticks(range(len(rows)), labels); ax.set_xlim(0, 1); ax.set_xlabel("challenger win rate (ties=0.5)")
        fig.tight_layout(); path = output / "relative_win_rate.png"; fig.savefig(path, dpi=180); plt.close(fig); created.append(str(path))
    return created
