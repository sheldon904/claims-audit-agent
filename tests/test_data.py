"""Dataset integrity + determinism tests."""

import json
from pathlib import Path

from claims_audit.engine import RuleEngine
from claims_audit.models import Claim, Finding
from claims_audit.rules import load_rules
from data.generate import N_CLAIMS, N_DEFECTIVE, generate, write_dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RS = load_rules()
ENGINE = RuleEngine(RS)


def test_generation_is_deterministic():
    a = generate(seed=42)
    b = generate(seed=42)
    a_ids = [c.claim_id for c in a["claims"]]
    b_ids = [c.claim_id for c in b["claims"]]
    assert a_ids == b_ids
    a_dump = [c.model_dump(mode="json") for c in a["claims"]]
    b_dump = [c.model_dump(mode="json") for c in b["claims"]]
    assert a_dump == b_dump


def test_counts():
    ds = generate()
    assert len(ds["claims"]) == N_CLAIMS
    defective = [cid for cid, fs in ds["ground_truth"].items() if fs]
    assert len(defective) == N_DEFECTIVE
    assert len(ds["holdout_ids"]) == 25


def test_ground_truth_matches_engine_exactly():
    """The clean-by-construction invariant: engine output == injected labels."""
    ds = generate()
    for claim in ds["claims"]:
        engine_keys = {(f.rule_id, tuple(sorted(f.line_refs))) for f in ENGINE.evaluate(claim)}
        gt_keys = {
            (f.rule_id, tuple(sorted(f.line_refs)))
            for f in ds["ground_truth"][claim.claim_id]
        }
        assert engine_keys == gt_keys, f"mismatch on {claim.claim_id}"


def test_holdout_covers_every_defect_category():
    ds = generate()
    gt = ds["ground_truth"]
    categories = set()
    for cid in ds["holdout_ids"]:
        for finding in gt[cid]:
            categories.add(finding.defect_type.value)
    assert categories == {
        "unbundling",
        "upcoding",
        "duplicate",
        "units_exceeded",
        "missing_modifier",
    }


def test_committed_files_present_and_valid():
    for name in ("claims.json", "ground_truth.json", "holdout.json", "manifest.json"):
        assert (DATA_DIR / name).exists(), f"{name} not committed"
    claims = json.loads((DATA_DIR / "claims.json").read_text(encoding="utf-8"))
    assert len(claims) == N_CLAIMS
    for c in claims:
        Claim.model_validate(c)
    holdout = json.loads((DATA_DIR / "holdout.json").read_text(encoding="utf-8"))
    for fs in holdout["ground_truth"].values():
        for finding in fs:
            Finding.model_validate(finding)


def test_committed_files_match_regeneration(tmp_path):
    """Committed data must equal a fresh generation (no drift)."""
    write_dataset(out_dir=tmp_path)
    for name in ("claims.json", "ground_truth.json", "holdout.json"):
        committed = (DATA_DIR / name).read_text(encoding="utf-8")
        fresh = (tmp_path / name).read_text(encoding="utf-8")
        assert committed == fresh, f"{name} is stale; run `python -m data.generate`"
