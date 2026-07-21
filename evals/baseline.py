"""Deterministic baseline arm.

``EngineAgent`` is the rule engine wrapped in the ``AuditAgent`` interface. It is
the arm the CI gate scores, because it is fully reproducible, needs no API key,
and — by the generator's clean-by-construction guarantee — should achieve
perfect precision/recall and a 0% fabrication rate on the frozen holdout. If it
ever doesn't, either a rule or the data drifted, and CI turns red.
"""

from __future__ import annotations

from claims_audit.engine import RuleEngine
from claims_audit.models import Claim, Finding
from claims_audit.rules import RuleSet, load_rules


class EngineAgent:
    """AuditAgent backed purely by the deterministic RuleEngine."""

    name = "engine"

    def __init__(self, ruleset: RuleSet | None = None):
        self.ruleset = ruleset or load_rules()
        self.engine = RuleEngine(self.ruleset)

    def audit(self, claim: Claim) -> list[Finding]:
        return self.engine.evaluate(claim)
