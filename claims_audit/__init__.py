"""Claims-audit-agent shared core.

Everything an agent needs that is *not* orchestration lives here so that the two
agent implementations (``agent_sdk`` on claude-agent-sdk, ``agent_graph`` on
LangGraph) are thin ports over an identical set of data models, tools, a
deterministic rule engine, and metrics.
"""

from claims_audit.engine import RuleEngine
from claims_audit.models import (
    Claim,
    ClaimLine,
    DefectType,
    Finding,
    Patient,
    Provider,
    Severity,
)
from claims_audit.rules import Rule, RuleSet, load_rules

__all__ = [
    "Claim",
    "ClaimLine",
    "DefectType",
    "Finding",
    "Patient",
    "Provider",
    "Severity",
    "Rule",
    "RuleSet",
    "load_rules",
    "RuleEngine",
]
