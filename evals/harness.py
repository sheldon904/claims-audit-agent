"""Eval harness.

The harness is deliberately agent-agnostic: anything with an
``audit(claim) -> list[Finding]`` method is an *arm* it can score. That is what
lets the exact same holdout and metrics judge the deterministic engine, the
claude-agent-sdk agent, and the LangGraph agent on equal footing.

It captures, per claim: the predicted findings, wall-clock latency, and (for LLM
arms) token usage so cost-per-claim can be reported. Metrics come from
``claims_audit.metrics``; nothing about scoring is arm-specific.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from claims_audit.metrics import EvalResult, score_dataset
from claims_audit.models import Claim, Finding
from claims_audit.rules import RuleSet, load_rules

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


# ---------------------------------------------------------------------------
# Arm protocol + usage accounting
# ---------------------------------------------------------------------------


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


class AuditAgent(Protocol):
    """Any audit arm the harness can score."""

    name: str

    def audit(self, claim: Claim) -> list[Finding]:
        """Return findings for one claim."""
        ...


@dataclass
class ArmResult:
    """Everything one arm produced over a dataset."""

    name: str
    config: dict
    predictions: dict[str, list[Finding]]
    latencies_ms: dict[str, float] = field(default_factory=dict)
    usage: dict[str, Usage] = field(default_factory=dict)
    metrics: EvalResult | None = None

    # --- derived reporting numbers ---
    @property
    def total_latency_ms(self) -> float:
        return sum(self.latencies_ms.values())

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / len(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def total_usage(self) -> Usage:
        out = Usage()
        for u in self.usage.values():
            out = out + u
        return out


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def _findings_from_json(items: list[dict]) -> list[Finding]:
    return [Finding.model_validate(it) for it in items]


def load_holdout(data_dir: Path = DATA_DIR) -> tuple[list[Claim], dict[str, list[Finding]]]:
    raw = json.loads((data_dir / "holdout.json").read_text(encoding="utf-8"))
    claims = [Claim.model_validate(c) for c in raw["claims"]]
    gt = {cid: _findings_from_json(fs) for cid, fs in raw["ground_truth"].items()}
    return claims, gt


def load_full(data_dir: Path = DATA_DIR) -> tuple[list[Claim], dict[str, list[Finding]]]:
    claims_raw = json.loads((data_dir / "claims.json").read_text(encoding="utf-8"))
    gt_raw = json.loads((data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    claims = [Claim.model_validate(c) for c in claims_raw]
    gt = {cid: _findings_from_json(fs) for cid, fs in gt_raw.items()}
    return claims, gt


# ---------------------------------------------------------------------------
# Running + scoring
# ---------------------------------------------------------------------------


def run_arm(
    agent: AuditAgent,
    claims: list[Claim],
    ground_truth: dict[str, list[Finding]],
    ruleset: RuleSet | None = None,
    config: dict | None = None,
    usage_of: Callable[[AuditAgent], Usage] | None = None,
) -> ArmResult:
    """Run one arm over ``claims`` and score it against ``ground_truth``.

    ``usage_of`` is an optional callable ``(agent) -> Usage`` read after each
    claim so LLM arms can report per-claim token usage; the deterministic engine
    simply omits it.
    """
    ruleset = ruleset or load_rules()
    result = ArmResult(name=agent.name, config=config or {}, predictions={})

    for claim in claims:
        before = usage_of(agent) if usage_of else None
        t0 = time.perf_counter()
        findings = agent.audit(claim)
        elapsed = (time.perf_counter() - t0) * 1000.0
        result.predictions[claim.claim_id] = findings
        result.latencies_ms[claim.claim_id] = elapsed
        if usage_of:
            after = usage_of(agent)
            result.usage[claim.claim_id] = Usage(
                after.input_tokens - before.input_tokens,
                after.output_tokens - before.output_tokens,
            )

    claims_by_id = {c.claim_id: c for c in claims}
    result.metrics = score_dataset(result.predictions, ground_truth, claims_by_id, ruleset)
    return result
