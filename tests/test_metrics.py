from claims_audit.metrics import score_claim, score_dataset
from claims_audit.models import Claim, ClaimLine, DefectType, Finding, Patient, Provider
from claims_audit.rules import load_rules

RS = load_rules()


def claim_with_lines(*line_ids):
    return Claim(
        claim_id="CLM-1",
        patient=Patient(patient_id="PT-1", year_of_birth=1980, sex="F"),
        provider=Provider(npi="1013001112", name="Cedar", specialty="family_medicine"),
        date_of_service="2025-03-01",
        lines=[ClaimLine(line_id=lid, cpt="99213", units=1, charge=0.0) for lid in line_ids],
    )


def f(rule_id, line_refs, claim_id="CLM-1", defect=DefectType.UNBUNDLING):
    return Finding(claim_id=claim_id, rule_id=rule_id, defect_type=defect, line_refs=line_refs)


def test_perfect_match():
    claim = claim_with_lines("L1", "L2")
    gt = [f("R001", ["L1", "L2"])]
    pred = [f("R001", ["L1", "L2"])]
    r = score_claim(pred, gt, claim, RS)
    assert r.precision == 1.0 and r.recall == 1.0 and r.fabrication_rate == 0.0


def test_partial_line_overlap_counts_as_match():
    claim = claim_with_lines("L1", "L2")
    gt = [f("R001", ["L1", "L2"])]
    pred = [f("R001", ["L1"])]  # overlaps -> match
    r = score_claim(pred, gt, claim, RS)
    assert r.true_positives == 1 and r.false_positives == 0


def test_wrong_rule_is_false_positive_and_false_negative():
    claim = claim_with_lines("L1", "L2")
    gt = [f("R001", ["L1", "L2"])]
    pred = [f("R002", ["L1", "L2"])]
    r = score_claim(pred, gt, claim, RS)
    assert r.false_positives == 1 and r.false_negatives == 1 and r.true_positives == 0


def test_fabricated_rule_id_counts_as_invalid_citation():
    claim = claim_with_lines("L1")
    pred = [f("R999", ["L1"])]  # rule does not exist
    r = score_claim(pred, [], claim, RS)
    assert r.invalid_citations == 1
    assert r.fabrication_rate == 1.0
    assert r.citation_validity == 0.0


def test_fabricated_line_ref_counts_as_invalid_citation():
    claim = claim_with_lines("L1")
    pred = [f("R001", ["L7"])]  # line L7 not on claim
    r = score_claim(pred, [], claim, RS)
    assert r.invalid_citations == 1
    assert r.fabrication_rate == 1.0


def test_missed_defect_is_false_negative():
    claim = claim_with_lines("L1", "L2")
    gt = [f("R001", ["L1", "L2"])]
    r = score_claim([], gt, claim, RS)
    assert r.false_negatives == 1 and r.recall == 0.0


def test_dataset_aggregation():
    claims = {"CLM-1": claim_with_lines("L1", "L2")}
    gt = {"CLM-1": [f("R001", ["L1", "L2"])]}
    pred = {"CLM-1": [f("R001", ["L1", "L2"])]}
    r = score_dataset(pred, gt, claims, RS)
    assert r.true_positives == 1 and r.precision == 1.0
