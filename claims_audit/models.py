"""Pydantic data models for claims and audit findings.

These are the contract shared by both agent implementations. ``Finding`` in
particular is the structured-output type that ``emit_finding`` validates every
agent-produced finding against, so a finding that does not conform is rejected
before it can ever reach the metrics.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    """How serious a detected defect is. Ordered low -> high for reporting."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DefectType(str, Enum):
    """The audit-defect taxonomy. Mirrors the injected-defect categories."""

    UNBUNDLING = "unbundling"
    UPCODING = "upcoding"
    DUPLICATE = "duplicate"
    UNITS_EXCEEDED = "units_exceeded"
    MISSING_MODIFIER = "missing_modifier"


# ---------------------------------------------------------------------------
# Claim structure
# ---------------------------------------------------------------------------


class Patient(BaseModel):
    """De-identified patient stub. No real PHI — synthetic values only."""

    patient_id: str
    year_of_birth: int = Field(ge=1900, le=2025)
    sex: str = Field(pattern="^(F|M|U)$")


class Provider(BaseModel):
    """Rendering provider stub."""

    npi: str = Field(description="Synthetic 10-digit National Provider Identifier")
    name: str
    specialty: str


class ClaimLine(BaseModel):
    """A single billed line item on a claim."""

    line_id: str = Field(description="Stable within-claim id, e.g. 'L1'")
    cpt: str = Field(description="CPT/HCPCS procedure code")
    units: int = Field(ge=1)
    modifiers: list[str] = Field(default_factory=list)
    diagnosis_pointers: list[str] = Field(
        default_factory=list,
        description="Pointers into Claim.diagnoses (e.g. 'A', 'B')",
    )
    charge: float = Field(ge=0.0)

    @field_validator("modifiers")
    @classmethod
    def _upper_modifiers(cls, v: list[str]) -> list[str]:
        return [m.strip().upper() for m in v if m.strip()]


class Claim(BaseModel):
    """A full claim: one date of service, one provider, one or more lines."""

    claim_id: str
    patient: Patient
    provider: Provider
    date_of_service: str = Field(description="ISO date, YYYY-MM-DD")
    diagnoses: list[str] = Field(
        default_factory=list, description="ICD-10-style diagnosis codes"
    )
    lines: list[ClaimLine]
    provider_notes: str = Field(default="", description="Free-text clinical note")

    def line_ids(self) -> set[str]:
        return {ln.line_id for ln in self.lines}

    def line(self, line_id: str) -> ClaimLine | None:
        for ln in self.lines:
            if ln.line_id == line_id:
                return ln
        return None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class Finding(BaseModel):
    """A single audit finding.

    Every finding MUST cite (a) a rule id that exists in the rule set and
    (b) at least one claim-line span that exists on the claim. Those two
    requirements are what the fabrication-rate / citation-validity metrics
    check. ``model_config`` forbids extra fields so an agent cannot smuggle
    unvalidated content into a finding.
    """

    model_config = {"extra": "forbid"}

    claim_id: str = Field(description="Claim this finding is about")
    rule_id: str = Field(description="Id of the violated rule, e.g. 'R001'")
    defect_type: DefectType
    line_refs: list[str] = Field(
        min_length=1,
        description="Claim-line ids the finding is about; must be non-empty",
    )
    severity: Severity = Severity.MEDIUM
    rationale: str = Field(
        default="", description="Short human-readable justification"
    )

    def key(self) -> tuple[str, str, frozenset[str]]:
        """Canonical identity used for exact-match dedup."""
        return (self.claim_id, self.rule_id, frozenset(self.line_refs))


# JSON Schema is exported so the README / tools can show the exact contract the
# structured-output tool enforces.
FINDING_JSON_SCHEMA = Finding.model_json_schema()
