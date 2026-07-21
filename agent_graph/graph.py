"""Agent v2 — the same auditor re-orchestrated as an explicit LangGraph.

Where ``agent_sdk`` lets the model drive an autonomous tool loop, here the
control flow is a fixed graph and the model is used only where judgment is
actually needed:

    intake ──▶ rule_scan ──▶ evidence_check ──▶ findings
   (fetch_    (lookup_rule   (check_patient_    (emit_
    claim)     + LLM scan)    history + verify)   finding)

The four nodes are the four shared tools re-sequenced. ``rule_scan`` is the one
LLM call: it reads the claim + rules (including the free-text note) and proposes
candidate findings via a forced structured tool call. ``evidence_check`` then
verifies every citation deterministically, so a hallucinated rule or line id is
dropped before it can become a finding — which is why this arm's fabrication
rate is structurally near zero.

The chat model is injectable (``model=`` in the constructor) so the whole graph
runs offline in tests with a scripted fake; production defaults to
``ChatAnthropic``. Requires the ``graph`` extra to import.
"""

from __future__ import annotations

from typing import Any, TypedDict

from claims_audit.models import Claim, Finding
from claims_audit.prompting import SYSTEM_PROMPT, audit_task_prompt
from claims_audit.rules import RuleSet, load_rules
from claims_audit.tools import (
    ToolContext,
    check_patient_history,
    emit_finding,
    fetch_claim,
    lookup_rule,
)
from evals.harness import Usage

DEFAULT_MODEL = "claude-sonnet-5"


class AuditState(TypedDict, total=False):
    claim_id: str
    claim: dict
    rules: list[dict]
    candidates: list[dict]
    confirmed: list[dict]
    findings: list[Finding]


def _report_findings_tool_schema() -> dict:
    """JSON-schema tool the model must call to report candidate findings."""
    return {
        "name": "report_findings",
        "description": (
            "Report every billing defect found in the claim. Each finding must "
            "cite an existing rule_id and the involved claim line_refs. Report an "
            "empty list if the claim is clean."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rule_id": {"type": "string"},
                            "defect_type": {"type": "string"},
                            "line_refs": {"type": "array", "items": {"type": "string"}},
                            "severity": {"type": "string"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["rule_id", "line_refs"],
                    },
                }
            },
            "required": ["findings"],
        },
    }


class LangGraphAuditAgent:
    """AuditAgent implemented as an explicit LangGraph."""

    def __init__(
        self,
        claims: list[Claim],
        ruleset: RuleSet | None = None,
        model: Any | None = None,
        model_name: str = DEFAULT_MODEL,
        thinking: bool = False,
        provider: str | None = None,
    ):
        self.ruleset = ruleset or load_rules()
        self.ctx = ToolContext.build(claims, self.ruleset)
        self.thinking = thinking
        self.model_name = model_name
        self.provider = provider
        self.name = "langgraph"
        self._usage = Usage()
        self._model = model if model is not None else self._build_model()
        self._graph = self._build_graph()

    # ---- harness interface ------------------------------------------------

    def audit(self, claim: Claim) -> list[Finding]:
        self.ctx.reset_emitted()
        state: AuditState = {"claim_id": claim.claim_id}
        out = self._graph.invoke(state)
        return list(out.get("findings", []))

    def usage(self) -> Usage:
        return Usage(self._usage.input_tokens, self._usage.output_tokens)

    # ---- model ------------------------------------------------------------

    def _build_model(self):
        """Build the chat model via the provider factory (anthropic | openrouter)."""
        from providers.chat import build_chat_model, build_config

        cfg = build_config(
            model=self.model_name, thinking=self.thinking, provider=self.provider
        )
        self.provider = cfg.provider
        return build_chat_model(cfg)

    # ---- graph ------------------------------------------------------------

    def _build_graph(self):
        from langgraph.graph import END, START, StateGraph

        g = StateGraph(AuditState)
        g.add_node("intake", self._intake)
        g.add_node("rule_scan", self._rule_scan)
        g.add_node("evidence_check", self._evidence_check)
        g.add_node("findings", self._findings)
        g.add_edge(START, "intake")
        g.add_edge("intake", "rule_scan")
        g.add_edge("rule_scan", "evidence_check")
        g.add_edge("evidence_check", "findings")
        g.add_edge("findings", END)
        return g.compile()

    # ---- nodes ------------------------------------------------------------

    def _intake(self, state: AuditState) -> AuditState:
        claim = fetch_claim(self.ctx, state["claim_id"])
        rules = lookup_rule(self.ctx)["rules"]
        return {"claim": claim, "rules": rules}

    def _rule_scan(self, state: AuditState) -> AuditState:
        """The single LLM call: propose candidate findings via a forced tool."""
        claim = Claim.model_validate(state["claim"])
        bound = self._model.bind_tools(
            [_report_findings_tool_schema()],
            tool_choice={"type": "tool", "name": "report_findings"},
        )
        messages = [
            ("system", SYSTEM_PROMPT),
            ("user", audit_task_prompt(claim, self.ruleset)),
        ]
        response = bound.invoke(messages)
        self._accumulate_usage(response)

        candidates: list[dict] = []
        for call in getattr(response, "tool_calls", []) or []:
            if call.get("name") == "report_findings":
                candidates.extend(call.get("args", {}).get("findings", []) or [])
        return {"candidates": candidates}

    def _evidence_check(self, state: AuditState) -> AuditState:
        """Verify each candidate's citations; drop anything unsupported."""
        claim = Claim.model_validate(state["claim"])
        # Cross-claim evidence is available to the node even if unused here.
        check_patient_history(self.ctx, claim.patient.patient_id, claim.claim_id)
        valid_line_ids = claim.line_ids()
        confirmed: list[dict] = []
        for cand in state.get("candidates", []):
            rule_id = cand.get("rule_id")
            line_refs = [str(x) for x in (cand.get("line_refs") or [])]
            if self.ruleset.by_id(rule_id) is None:
                continue  # hallucinated rule
            if not line_refs or any(ref not in valid_line_ids for ref in line_refs):
                continue  # hallucinated / missing line span
            rule = self.ruleset.by_id(rule_id)
            confirmed.append(
                {
                    "claim_id": claim.claim_id,
                    "rule_id": rule_id,
                    "defect_type": cand.get("defect_type") or rule.defect_type.value,
                    "line_refs": sorted(set(line_refs)),
                    "severity": cand.get("severity") or rule.severity.value,
                    "rationale": cand.get("rationale") or "",
                }
            )
        return {"confirmed": confirmed}

    def _findings(self, state: AuditState) -> AuditState:
        for cand in state.get("confirmed", []):
            emit_finding(self.ctx, cand)
        claim_id = state["claim_id"]
        return {"findings": [f for f in self.ctx.emitted if f.claim_id == claim_id]}

    # ---- usage ------------------------------------------------------------

    def _accumulate_usage(self, response) -> None:
        meta = getattr(response, "usage_metadata", None) or {}
        self._usage = Usage(
            self._usage.input_tokens + int(meta.get("input_tokens", 0)),
            self._usage.output_tokens + int(meta.get("output_tokens", 0)),
        )
