"""End-to-end OpenRouter run-path test — mocks ONLY the network call.

This exercises the exact pipeline the real ``make eval-openrouter`` command runs:

    run_eval.run_one(provider="openrouter")
        -> providers.chat.build_config  (resolves OpenRouter, maps the model)
        -> agent_graph.LangGraphAuditAgent  (intake->rule_scan->evidence_check->findings)
        -> claims_audit.metrics  (precision/recall/fabrication/citation)
        -> evals.reporting.arm_row  (the populated results row)

Only ``build_chat_model`` is swapped for a test double that returns findings in a
real ChatOpenAI-shaped response (``tool_calls`` + ``usage_metadata``). Everything
else — provider resolution, graph execution, citation verification, scoring, cost
accounting, row rendering — is the real code path. So when a real
``OPENROUTER_API_KEY`` is supplied, the only untested surface is the literal HTTPS
call, and the table-population step is guaranteed to run.

The double is an *oracle* (it returns the engine's findings) purely so the scored
row is meaningful; it is not a claim about any model's real accuracy.
"""

import json

import pytest

from claims_audit.engine import RuleEngine
from claims_audit.models import Claim
from claims_audit.rules import load_rules

RS = load_rules()
ENGINE = RuleEngine(RS)


def _extract_claim(prompt_text: str) -> Claim:
    """Pull the claim JSON back out of the rendered audit prompt."""
    marker = "CLAIM:\n"
    start = prompt_text.index(marker) + len(marker)
    end = prompt_text.index("\n\nFor each defect", start)
    return Claim.model_validate(json.loads(prompt_text[start:end]))


class _OracleAIMessage:
    """Mimics a langchain AIMessage from a tool-calling ChatOpenAI response."""

    def __init__(self, findings):
        self.tool_calls = [{"name": "report_findings", "args": {"findings": findings}}]
        self.usage_metadata = {"input_tokens": 800, "output_tokens": 60}


class _OracleModel:
    """Test double for the OpenRouter chat model (returns engine findings)."""

    def bind_tools(self, tools, tool_choice=None):
        return self

    def invoke(self, messages):
        claim = _extract_claim(messages[-1][1])
        findings = [
            {
                "rule_id": f.rule_id,
                "defect_type": f.defect_type.value,
                "line_refs": list(f.line_refs),
                "severity": f.severity.value,
                "rationale": f.rationale,
            }
            for f in ENGINE.evaluate(claim)
        ]
        return _OracleAIMessage(findings)


def test_openrouter_graph_run_path_populates_a_scored_row(monkeypatch):
    pytest.importorskip("langgraph")
    pytest.importorskip("langchain_openai")

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    # swap ONLY the network-bound model builder
    import providers.chat as pc

    monkeypatch.setattr(pc, "build_chat_model", lambda cfg: _OracleModel())

    from evals.reporting import arm_row
    from evals.run_eval import run_one

    result = run_one(
        arm="graph",
        thinking=True,
        dataset="holdout",
        model="claude-sonnet-5",
        limit=8,
        provider="openrouter",
    )

    # the full pipeline produced metrics and captured usage/cost
    assert result.metrics is not None
    m = result.metrics.as_dict()
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["fabrication_rate"] == 0.0
    assert m["citation_validity"] == 1.0
    assert result.total_usage.input_tokens > 0  # -> cost/claim is computable

    row = arm_row(result)
    assert row["provider"] == "openrouter"
    assert row["sdk"] == "langgraph · openrouter"
    assert row["thinking"] == "on"
    assert row["model"] == "claude-sonnet-5"
    assert row["precision"] == 1.0
    assert row["cost_per_claim_usd"] is not None


def test_openrouter_provider_resolution_from_env(monkeypatch):
    """--provider auto picks OpenRouter when only OPENROUTER_API_KEY is present."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    from evals.run_eval import _provider_key_present
    from providers.chat import resolve_provider

    assert resolve_provider("auto") == "openrouter"
    assert _provider_key_present("openrouter") is True
    assert _provider_key_present("anthropic") is False
