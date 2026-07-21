"""Offline agent tests — no API key required.

The LangGraph arm is exercised end-to-end with a scripted fake chat model so the
graph's control flow and the evidence-check verification are covered for free in
CI. The claude-agent-sdk arm is import-guarded and only its tool wiring is
checked (running its loop needs the Claude Code CLI + a key).
"""

import pytest

from claims_audit.models import Claim, ClaimLine, Patient, Provider
from claims_audit.rules import load_rules

RS = load_rules()


def _ncci_pair_claim() -> Claim:
    return Claim(
        claim_id="CLM-X",
        patient=Patient(patient_id="PT-1", year_of_birth=1980, sex="F"),
        provider=Provider(npi="1013001112", name="Cedar", specialty="family_medicine"),
        date_of_service="2025-03-01",
        diagnoses=["I10"],
        lines=[
            ClaimLine(line_id="L1", cpt="80053", units=1, charge=38.0),
            ClaimLine(line_id="L2", cpt="80048", units=1, charge=24.0),
        ],
        provider_notes="labs drawn",
    )


class _FakeAIMessage:
    def __init__(self, findings):
        self.tool_calls = [{"name": "report_findings", "args": {"findings": findings}}]
        self.usage_metadata = {"input_tokens": 120, "output_tokens": 30}


class _FakeChatModel:
    """Stands in for ChatAnthropic. Returns a scripted set of candidate findings."""

    def __init__(self, findings):
        self._findings = findings

    def bind_tools(self, tools, tool_choice=None):
        return self  # ignore binding; we always return the scripted output

    def invoke(self, messages):
        return _FakeAIMessage(self._findings)


def test_langgraph_agent_end_to_end_and_drops_hallucinations():
    pytest.importorskip("langgraph")
    from agent_graph.graph import LangGraphAuditAgent

    claim = _ncci_pair_claim()
    scripted = [
        {"rule_id": "R001", "line_refs": ["L1", "L2"], "rationale": "real defect"},
        {"rule_id": "R999", "line_refs": ["L1"], "rationale": "hallucinated rule"},
        {"rule_id": "R001", "line_refs": ["L9"], "rationale": "hallucinated line"},
    ]
    agent = LangGraphAuditAgent([claim], ruleset=RS, model=_FakeChatModel(scripted))
    findings = agent.audit(claim)

    # Only the well-cited finding survives evidence_check.
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "R001"
    assert set(f.line_refs) == {"L1", "L2"}
    # Every surviving finding has a valid citation (0% fabrication by construction).
    assert RS.by_id(f.rule_id) is not None
    assert set(f.line_refs) <= claim.line_ids()
    # usage was captured
    assert agent.usage().input_tokens == 120


def test_langgraph_clean_claim_yields_no_findings():
    pytest.importorskip("langgraph")
    from agent_graph.graph import LangGraphAuditAgent

    claim = _ncci_pair_claim()
    agent = LangGraphAuditAgent([claim], ruleset=RS, model=_FakeChatModel([]))
    assert agent.audit(claim) == []


def test_claude_sdk_agent_tool_wiring():
    pytest.importorskip("claude_agent_sdk")
    from agent_sdk.agent import ClaudeSDKAuditAgent

    claim = _ncci_pair_claim()
    agent = ClaudeSDKAuditAgent([claim], ruleset=RS)
    server = agent._build_server()
    assert server is not None
    assert agent.name == "claude-agent-sdk"
