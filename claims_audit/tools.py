"""The four audit tools, implemented once and shared by both agents.

``fetch_claim``, ``lookup_rule``, ``check_patient_history`` and ``emit_finding``
are pure functions over a :class:`ToolContext`. ``agent_sdk`` registers them as
claude-agent-sdk ``@tool`` handlers; ``agent_graph`` calls the same functions
from graph nodes. Keeping the implementations here is what makes the two agents
genuine ports of one core rather than two separate programs.

``emit_finding`` performs *structural* validation only (the Pydantic/JSON-Schema
contract). It deliberately does NOT reject a structurally-valid finding that
cites a non-existent rule or line: catching those is the job of the
fabrication-rate metric, and silently dropping them would make that metric
meaningless.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import ValidationError

from claims_audit.models import Claim, Finding
from claims_audit.rules import RuleSet


@dataclass
class ToolContext:
    """Everything the tools read from / write to for one audit session."""

    claims: dict[str, Claim]
    ruleset: RuleSet
    # patient_id -> list of claim_ids, for check_patient_history
    _history: dict[str, list[str]] = field(default_factory=dict)
    # findings accepted during this session
    emitted: list[Finding] = field(default_factory=list)

    @classmethod
    def build(cls, claims: list[Claim], ruleset: RuleSet) -> ToolContext:
        history: dict[str, list[str]] = defaultdict(list)
        for c in claims:
            history[c.patient.patient_id].append(c.claim_id)
        return cls(
            claims={c.claim_id: c for c in claims},
            ruleset=ruleset,
            _history=dict(history),
        )

    def reset_emitted(self) -> None:
        self.emitted = []


# ---------------------------------------------------------------------------
# Tool implementations. Each returns plain JSON-serialisable dicts so they drop
# straight into either SDK's tool-result channel.
# ---------------------------------------------------------------------------


def fetch_claim(ctx: ToolContext, claim_id: str) -> dict:
    """Return the full claim record for ``claim_id``."""
    claim = ctx.claims.get(claim_id)
    if claim is None:
        return {"error": f"claim {claim_id!r} not found"}
    return claim.model_dump()


def lookup_rule(
    ctx: ToolContext,
    rule_id: str | None = None,
    code: str | None = None,
) -> dict:
    """Look up rules by id, by affected CPT code, or return them all.

    * ``rule_id`` given -> that single rule (or an error).
    * ``code`` given -> every rule whose params reference that code.
    * neither -> the entire rule set (ids + descriptions).
    """
    if rule_id is not None:
        rule = ctx.ruleset.by_id(rule_id)
        if rule is None:
            return {"error": f"rule {rule_id!r} not found"}
        return {"rule": rule.model_dump()}

    if code is not None:
        matches = []
        for r in ctx.ruleset:
            p = r.params
            referenced = {
                str(p.get("code")),
                str(p.get("code_a")),
                str(p.get("code_b")),
                *[str(c) for c in p.get("em_codes", [])],
                *[str(c) for c in p.get("procedure_codes", [])],
            }
            if code in referenced:
                matches.append(r.model_dump())
        return {"rules": matches}

    return {
        "rules": [
            {"id": r.id, "type": r.type.value, "description": r.description.strip()}
            for r in ctx.ruleset
        ]
    }


def check_patient_history(
    ctx: ToolContext, patient_id: str, exclude_claim_id: str | None = None
) -> dict:
    """Return other claims for the same patient (evidence for cross-claim checks)."""
    claim_ids = ctx._history.get(patient_id, [])
    prior = []
    for cid in claim_ids:
        if cid == exclude_claim_id:
            continue
        c = ctx.claims[cid]
        prior.append(
            {
                "claim_id": c.claim_id,
                "date_of_service": c.date_of_service,
                "lines": [
                    {"cpt": ln.cpt, "units": ln.units, "modifiers": ln.modifiers}
                    for ln in c.lines
                ],
            }
        )
    return {"patient_id": patient_id, "prior_claims": prior}


def emit_finding(ctx: ToolContext, finding: dict) -> dict:
    """Validate a finding against the Pydantic/JSON-Schema contract and record it.

    Returns ``{"accepted": True, ...}`` on structural success, or
    ``{"accepted": False, "errors": [...]}`` with the validation errors so the
    agent can correct and retry.
    """
    try:
        model = Finding.model_validate(finding)
    except ValidationError as exc:
        return {
            "accepted": False,
            "errors": [
                {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()
            ],
        }
    ctx.emitted.append(model)
    return {"accepted": True, "finding_key": list(map(str, model.key()[:2]))}


# JSON-Schema-shaped tool descriptors, reused by both agents so the wire-level
# contract is identical across SDKs.
TOOL_SCHEMAS: dict[str, dict] = {
    "fetch_claim": {
        "description": "Fetch the full claim record (patient stub, lines, notes) by id.",
        "input_schema": {
            "type": "object",
            "properties": {"claim_id": {"type": "string"}},
            "required": ["claim_id"],
        },
    },
    "lookup_rule": {
        "description": (
            "Look up audit rules. Provide rule_id for one rule, code for all rules "
            "referencing a CPT code, or neither to list every rule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string"},
                "code": {"type": "string"},
            },
        },
    },
    "check_patient_history": {
        "description": "Return the patient's other claims to check for cross-claim duplicates/frequency.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_id": {"type": "string"},
                "exclude_claim_id": {"type": "string"},
            },
            "required": ["patient_id"],
        },
    },
    "emit_finding": {
        "description": (
            "Emit one audit finding. Must cite an existing rule_id and at least one "
            "existing claim line_ref. Validated against the Finding JSON Schema."
        ),
        "input_schema": Finding.model_json_schema(),
    },
}
