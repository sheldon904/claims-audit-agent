"""Rule-set loading and typed rule models.

Rules are authored as machine-readable YAML in ``rules/audit_rules.yaml`` and
loaded into typed ``Rule`` objects. The YAML is the single source of truth: the
deterministic engine, both agents' ``lookup_rule`` tool, and the eval all read
the same file. This mirrors how a statute/compliance engine keeps its logic in
data rather than code.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from claims_audit.models import DefectType, Severity

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "audit_rules.yaml"


class RuleType(str, Enum):
    """Kinds of edits the engine knows how to evaluate."""

    NCCI_PAIR = "ncci_pair"
    MUE_UNITS = "mue_units"
    DUPLICATE = "duplicate"
    MODIFIER_REQUIRED = "modifier_required"
    UPCODING_EM = "upcoding_em"


class Rule(BaseModel):
    """One machine-readable audit rule."""

    id: str
    type: RuleType
    defect_type: DefectType
    severity: Severity = Severity.MEDIUM
    description: str
    # Free-form typed params; each RuleType interprets its own keys.
    params: dict = Field(default_factory=dict)


class RuleSet(BaseModel):
    """A collection of rules with id-based lookup."""

    rules: list[Rule]

    def by_id(self, rule_id: str) -> Rule | None:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None

    def ids(self) -> set[str]:
        return {r.id for r in self.rules}

    def of_type(self, rule_type: RuleType) -> list[Rule]:
        return [r for r in self.rules if r.type == rule_type]

    def __iter__(self):
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)


def load_rules(path: str | Path | None = None) -> RuleSet:
    """Load and validate the rule set from YAML."""
    p = Path(path) if path else DEFAULT_RULES_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    rules = [Rule(**item) for item in raw["rules"]]
    ids = [r.id for r in rules]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"Duplicate rule ids in {p}: {dupes}")
    return RuleSet(rules=rules)
