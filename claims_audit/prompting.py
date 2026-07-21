"""Shared prompt + serialization helpers for the LLM agent arms.

Both agents send the model the same task framing and the same rendered view of a
claim and the rule set, so any accuracy difference between them is attributable
to orchestration, not to prompt drift.
"""

from __future__ import annotations

import json

from claims_audit.models import Claim
from claims_audit.rules import RuleSet

SYSTEM_PROMPT = """\
You are a medical-claims line-item auditor. You examine one claim at a time and \
report billing defects, citing the exact rule and claim lines involved.

You audit against a fixed, machine-readable rule set. You may ONLY report a \
defect that corresponds to one of those rules. For every finding you MUST:
  * cite the rule_id of the violated rule (it must be a real rule id), and
  * cite the line_refs (the claim's line ids, e.g. "L1") the defect involves.

Never invent a rule id or a line id. If no rule is violated, report nothing. \
Prefer precision: only report a defect when the rule's conditions are clearly \
met. For E/M up-coding rules, read the free-text provider note and decide \
whether it documents the level of service billed.

Defect categories: unbundling, upcoding, duplicate, units_exceeded, \
missing_modifier. Use the defect_type from the cited rule.
"""


def render_rules(ruleset: RuleSet) -> str:
    """Compact, model-friendly rendering of every rule."""
    lines = []
    for r in ruleset:
        params = json.dumps(r.params, separators=(",", ":"))
        lines.append(
            f"- {r.id} [{r.type.value}] defect={r.defect_type.value} "
            f"severity={r.severity.value}: {' '.join(r.description.split())} "
            f"params={params}"
        )
    return "\n".join(lines)


def render_claim(claim: Claim) -> str:
    """Render a claim as compact JSON the model can reason over."""
    return json.dumps(claim.model_dump(mode="json"), indent=2)


def audit_task_prompt(claim: Claim, ruleset: RuleSet) -> str:
    """The per-claim instruction used by both agents."""
    return (
        f"Audit this claim and emit one finding per distinct defect.\n\n"
        f"RULES:\n{render_rules(ruleset)}\n\n"
        f"CLAIM:\n{render_claim(claim)}\n\n"
        f"For each defect, cite the rule_id and the involved line_refs. "
        f"If the claim is clean, emit no findings."
    )
