"""Per-rule-type unit tests for the deterministic engine.

Each rule type gets a positive case (defect present -> flagged) and a negative
case (the near-miss that must NOT be flagged), because a checker that only ever
fires is useless — the negative cases are what protect precision.
"""

from claims_audit.engine import RuleEngine
from claims_audit.models import Claim, ClaimLine, Patient, Provider
from claims_audit.rules import load_rules

RS = load_rules()
ENGINE = RuleEngine(RS)


def make_claim(lines, notes="", claim_id="CLM-T"):
    return Claim(
        claim_id=claim_id,
        patient=Patient(patient_id="PT-1", year_of_birth=1980, sex="F"),
        provider=Provider(npi="1013001112", name="Cedar", specialty="family_medicine"),
        date_of_service="2025-03-01",
        diagnoses=["I10"],
        lines=[ClaimLine(charge=0.0, **ln) for ln in lines],
        provider_notes=notes,
    )


def rule_ids(claim):
    return sorted(f.rule_id for f in ENGINE.evaluate(claim))


# ---- NCCI pair (unbundling) -----------------------------------------------

def test_ncci_pair_flagged():
    claim = make_claim(
        [{"line_id": "L1", "cpt": "80053", "units": 1}, {"line_id": "L2", "cpt": "80048", "units": 1}]
    )
    assert rule_ids(claim) == ["R001"]


def test_ncci_pair_bypassed_by_override_modifier():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "80053", "units": 1},
            {"line_id": "L2", "cpt": "80048", "units": 1, "modifiers": ["59"]},
        ]
    )
    assert rule_ids(claim) == []


# ---- MUE units ------------------------------------------------------------

def test_units_over_limit_flagged():
    claim = make_claim([{"line_id": "L1", "cpt": "97110", "units": 6}])
    assert rule_ids(claim) == ["R005"]


def test_units_at_limit_not_flagged():
    claim = make_claim([{"line_id": "L1", "cpt": "97110", "units": 4}])
    assert rule_ids(claim) == []


def test_units_aggregate_across_lines():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "97110", "units": 3},
            {"line_id": "L2", "cpt": "97110", "units": 3},
        ]
    )
    # 3+3 = 6 > 4 (units) AND identical code+mods twice (duplicate).
    assert rule_ids(claim) == ["R005", "R009"]


# ---- Duplicate ------------------------------------------------------------

def test_duplicate_flagged():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "96372", "units": 1},
            {"line_id": "L2", "cpt": "96372", "units": 1},
        ]
    )
    assert rule_ids(claim) == ["R009"]


def test_duplicate_bypassed_by_distinguishing_modifier():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "96372", "units": 1},
            {"line_id": "L2", "cpt": "96372", "units": 1, "modifiers": ["76"]},
        ]
    )
    assert rule_ids(claim) == []


# ---- Missing modifier -----------------------------------------------------

def test_missing_modifier_flagged():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "99213", "units": 1},
            {"line_id": "L2", "cpt": "96372", "units": 1},
        ]
    )
    assert rule_ids(claim) == ["R010"]


def test_modifier_25_present_not_flagged():
    claim = make_claim(
        [
            {"line_id": "L1", "cpt": "99213", "units": 1, "modifiers": ["25"]},
            {"line_id": "L2", "cpt": "96372", "units": 1},
        ]
    )
    assert rule_ids(claim) == []


# ---- Upcoding (note-based) -------------------------------------------------

def test_upcoding_flagged_when_note_unsupported():
    claim = make_claim(
        [{"line_id": "L1", "cpt": "99215", "units": 1}],
        notes="Brief stable refill visit.",
    )
    assert rule_ids(claim) == ["R011"]


def test_upcoding_not_flagged_when_note_supports():
    claim = make_claim(
        [{"line_id": "L1", "cpt": "99215", "units": 1}],
        notes="High complexity decision-making; 45 min spent.",
    )
    assert rule_ids(claim) == []


def test_clean_claim_yields_nothing():
    claim = make_claim([{"line_id": "L1", "cpt": "99213", "units": 1}], notes="stable")
    assert rule_ids(claim) == []


def test_findings_carry_valid_citations():
    claim = make_claim(
        [{"line_id": "L1", "cpt": "80053", "units": 1}, {"line_id": "L2", "cpt": "80048", "units": 1}]
    )
    for f in ENGINE.evaluate(claim):
        assert RS.by_id(f.rule_id) is not None
        assert set(f.line_refs) <= claim.line_ids()
