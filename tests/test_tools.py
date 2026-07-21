from claims_audit.rules import load_rules
from claims_audit.tools import (
    ToolContext,
    check_patient_history,
    emit_finding,
    fetch_claim,
    lookup_rule,
)
from data.generate import generate

RS = load_rules()


def _ctx():
    ds = generate()
    return ToolContext.build(ds["claims"], RS)


def test_fetch_claim_hit_and_miss():
    ctx = _ctx()
    some_id = next(iter(ctx.claims))
    assert fetch_claim(ctx, some_id)["claim_id"] == some_id
    assert "error" in fetch_claim(ctx, "NOPE")


def test_lookup_rule_by_id_code_and_all():
    ctx = _ctx()
    assert lookup_rule(ctx, rule_id="R001")["rule"]["id"] == "R001"
    assert "error" in lookup_rule(ctx, rule_id="R999")
    by_code = lookup_rule(ctx, code="80053")["rules"]
    assert any(r["id"] == "R001" for r in by_code)
    assert len(lookup_rule(ctx)["rules"]) == len(RS)


def test_check_patient_history_excludes_self():
    ctx = _ctx()
    # find a patient with >1 claim
    from collections import Counter

    counts = Counter(c.patient.patient_id for c in ctx.claims.values())
    pid = next(p for p, n in counts.items() if n > 1)
    claim = next(c for c in ctx.claims.values() if c.patient.patient_id == pid)
    hist = check_patient_history(ctx, pid, exclude_claim_id=claim.claim_id)
    assert all(pc["claim_id"] != claim.claim_id for pc in hist["prior_claims"])


def test_emit_finding_accepts_valid():
    ctx = _ctx()
    res = emit_finding(
        ctx,
        {
            "claim_id": "CLM-00001",
            "rule_id": "R001",
            "defect_type": "unbundling",
            "line_refs": ["L1"],
            "severity": "high",
        },
    )
    assert res["accepted"] is True
    assert len(ctx.emitted) == 1


def test_emit_finding_rejects_structurally_invalid():
    ctx = _ctx()
    res = emit_finding(
        ctx,
        {"claim_id": "CLM-1", "rule_id": "R001", "defect_type": "unbundling", "line_refs": []},
    )
    assert res["accepted"] is False
    assert res["errors"]
    assert ctx.emitted == []


def test_emit_finding_records_but_does_not_semantically_validate():
    """A structurally-valid finding citing a bogus rule is still recorded, so the
    fabrication metric can catch it (silently dropping it would hide fabrication)."""
    ctx = _ctx()
    res = emit_finding(
        ctx,
        {
            "claim_id": "CLM-1",
            "rule_id": "R999",  # not a real rule
            "defect_type": "unbundling",
            "line_refs": ["L1"],
        },
    )
    assert res["accepted"] is True
    assert len(ctx.emitted) == 1
