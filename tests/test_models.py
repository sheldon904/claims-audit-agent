import pytest
from pydantic import ValidationError

from claims_audit.models import (
    Claim,
    ClaimLine,
    DefectType,
    Finding,
    Patient,
    Provider,
    Severity,
)


def _claim() -> Claim:
    return Claim(
        claim_id="CLM-1",
        patient=Patient(patient_id="PT-1", year_of_birth=1980, sex="F"),
        provider=Provider(npi="1013001112", name="Cedar", specialty="family_medicine"),
        date_of_service="2025-03-01",
        diagnoses=["I10"],
        lines=[ClaimLine(line_id="L1", cpt="99213", units=1, charge=118.0)],
        provider_notes="stable follow-up",
    )


def test_finding_roundtrip():
    f = Finding(
        claim_id="CLM-1",
        rule_id="R001",
        defect_type=DefectType.UNBUNDLING,
        line_refs=["L1", "L2"],
        severity=Severity.HIGH,
    )
    assert f.key() == ("CLM-1", "R001", frozenset({"L1", "L2"}))
    assert Finding.model_validate(f.model_dump()) == f


def test_finding_requires_nonempty_line_refs():
    with pytest.raises(ValidationError):
        Finding(claim_id="C", rule_id="R001", defect_type="unbundling", line_refs=[])


def test_finding_forbids_extra_fields():
    with pytest.raises(ValidationError):
        Finding(
            claim_id="C",
            rule_id="R001",
            defect_type="unbundling",
            line_refs=["L1"],
            bogus_field=123,
        )


def test_claim_line_lookup_and_modifier_normalisation():
    claim = _claim()
    claim.lines[0].modifiers = [" 59 ", "25"]
    ln = ClaimLine.model_validate(claim.lines[0].model_dump())
    assert ln.modifiers == ["59", "25"]
    assert claim.line("L1") is not None
    assert claim.line("does-not-exist") is None
    assert claim.line_ids() == {"L1"}


def test_invalid_sex_rejected():
    with pytest.raises(ValidationError):
        Patient(patient_id="PT-1", year_of_birth=1980, sex="X")
