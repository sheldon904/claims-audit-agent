"""Cost model and results-table rendering.

Prices are list prices in USD per million tokens and are easy to edit in one
place. They are only used to turn measured token usage into a $/claim figure for
the README table; nothing in the eval logic depends on them.
"""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness import ArmResult

# USD per 1M tokens. Update to match current pricing for the model you run.
PRICING = {
    "claude-opus-4-8": {"input": 15.0, "output": 75.0},
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}
DEFAULT_MODEL = "claude-sonnet-5"


def cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    p = PRICING.get(model)
    if not p:
        return 0.0
    return input_tokens / 1e6 * p["input"] + output_tokens / 1e6 * p["output"]


def arm_row(arm: ArmResult) -> dict:
    """Flatten an ArmResult into a single reporting row."""
    m = arm.metrics.as_dict() if arm.metrics else {}
    model = arm.config.get("model", "")
    usage = arm.total_usage
    n = max(1, len(arm.predictions))
    total_cost = cost_usd(usage.input_tokens, usage.output_tokens, model)
    return {
        "arm": arm.name,
        "sdk": arm.config.get("sdk", arm.name),
        "thinking": arm.config.get("thinking", "n/a"),
        "model": model or "n/a",
        "precision": m.get("precision"),
        "recall": m.get("recall"),
        "f1": m.get("f1"),
        "citation_validity": m.get("citation_validity"),
        "fabrication_rate": m.get("fabrication_rate"),
        "avg_latency_ms": round(arm.avg_latency_ms, 1),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_per_claim_usd": round(total_cost / n, 5),
    }


def render_markdown_table(rows: list[dict]) -> str:
    """Render the results table used in the README."""
    headers = [
        ("sdk", "SDK / Arm"),
        ("thinking", "Thinking"),
        ("model", "Model"),
        ("precision", "Precision"),
        ("recall", "Recall"),
        ("f1", "F1"),
        ("citation_validity", "Citation valid."),
        ("fabrication_rate", "Fabrication"),
        ("avg_latency_ms", "Latency (ms)"),
        ("cost_per_claim_usd", "$/claim"),
    ]

    def fmt(key, val):
        if val is None:
            return "—"
        if key in {"precision", "recall", "f1", "citation_validity", "fabrication_rate"}:
            return f"{val:.3f}"
        if key == "cost_per_claim_usd":
            return f"${val:.5f}"
        return str(val)

    head = "| " + " | ".join(h[1] for h in headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = []
    for r in rows:
        body.append("| " + " | ".join(fmt(k, r.get(k)) for k, _ in headers) + " |")
    return "\n".join([head, sep, *body])


def save_results(rows: list[dict], out_path: Path) -> None:
    out_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
