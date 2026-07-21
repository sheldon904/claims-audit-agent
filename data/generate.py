"""Synthetic claims generator.

Design goals
------------
1. NO real health data. Every patient, provider, note, and code relationship is
   synthetic; CPT numbers are opaque identifiers whose meaning is defined solely
   by ``rules/audit_rules.yaml``.
2. Deterministic. A fixed seed produces byte-identical output, so the committed
   ``data/*.json`` is reproducible and diffable.
3. Clean by construction. Non-defective claims are assembled only from
   combinations the rule engine cannot flag. Defective claims are assembled to
   contain *exactly* the intended defect(s).
4. Self-verifying ground truth. After generation, the deterministic engine is
   run over every claim and its findings are asserted to equal the injected
   labels. This is the "two-database holdout" discipline: the labels and an
   independent checker must agree before anything is written to disk.

Run:  python -m data.generate   (or the ``claims-generate`` console script)
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from claims_audit.engine import RuleEngine
from claims_audit.models import Claim, ClaimLine, Finding, Patient, Provider
from claims_audit.rules import RuleSet, load_rules

SEED = 42
N_CLAIMS = 200
N_DEFECTIVE = 40
HOLDOUT_SIZE = 25
DATA_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Reference pools (all synthetic)
# ---------------------------------------------------------------------------

PROVIDERS = [
    ("1013001112", "Cedar Family Medicine", "family_medicine"),
    ("1013002223", "Lakeside Internal Medicine", "internal_medicine"),
    ("1013003334", "Harbor Cardiology", "cardiology"),
    ("1013004445", "Summit Orthopedics", "orthopedics"),
    ("1013005556", "Rivertown Physical Therapy", "physical_therapy"),
]

DIAGNOSES = [
    "E11.9",   # type 2 diabetes, no complication
    "I10",     # essential hypertension
    "M54.50",  # low back pain
    "R51.9",   # headache
    "Z00.00",  # general adult exam
    "J06.9",   # acute upper respiratory infection
    "M25.561", # pain in right knee
    "M17.11",  # osteoarthritis right knee
    "E78.5",   # hyperlipidemia
    "R07.9",   # chest pain
]

CHARGES = {
    "99213": 118.0, "99214": 176.0, "99215": 235.0,
    "80048": 24.0, "80053": 38.0, "85025": 21.0, "36415": 12.0,
    "93000": 55.0, "93005": 30.0, "93010": 28.0,
    "97110": 42.0, "97140": 45.0,
    "96372": 34.0, "J1885": 18.0,
    "20610": 128.0, "11042": 165.0,
}

def _note(rng: random.Random, kind: str) -> str:
    """Build a free-text provider note. ``kind`` steers documentation content."""
    opener = rng.choice(
        [
            "Established patient presents for follow-up.",
            "Patient seen in clinic today.",
            "Return visit for ongoing management.",
            "Scheduled follow-up appointment.",
        ]
    )
    if kind == "low":
        body = rng.choice(
            [
                "Stable on current regimen. Straightforward, low complexity. No new concerns.",
                "Brief visit for medication refill. Stable, minimal problem addressed.",
                "Doing well overall. Routine check, self-limited issue reviewed.",
            ]
        )
    elif kind == "moderate":
        body = rng.choice(
            [
                "Two chronic problems reviewed with adjustment; moderate complexity decision-making, total time 30 min.",
                "Moderate medical decision making today; medication titrated and labs ordered.",
            ]
        )
    elif kind == "high":
        body = rng.choice(
            [
                "Multiple chronic conditions poorly controlled; high complexity decision-making, total time 45 min.",
                "Extensive review; high medical decision making with new prescription drug management, 40 min spent.",
            ]
        )
    elif kind == "under_moderate":
        # Uses a 99214 but the note does NOT support it.
        body = rng.choice(
            [
                "Quick check-in, patient stable, no changes made. Straightforward.",
                "Brief refill visit, one stable problem, minimal exam.",
            ]
        )
    elif kind == "under_high":
        # Uses a 99215 but the note does NOT support it.
        body = rng.choice(
            [
                "Short visit for a single stable issue. No new problems, straightforward.",
                "Routine refill, patient doing well, brief encounter.",
            ]
        )
    else:  # neutral / procedural
        body = rng.choice(
            [
                "Procedure performed as documented; patient tolerated well.",
                "Specimen collected and sent to lab. No complications.",
                "Diagnostics obtained and reviewed with patient.",
            ]
        )
    return f"{opener} {body}"


# ---------------------------------------------------------------------------
# Builders. Each returns (lines, note_kind, intended) where ``intended`` is a
# list of (rule_id, [line_ids]) tuples describing the defects present (possibly
# empty for a clean claim).
# ---------------------------------------------------------------------------

def _line(line_id, cpt, units=1, modifiers=None, dx=("A",)):
    return ClaimLine(
        line_id=line_id,
        cpt=cpt,
        units=units,
        modifiers=list(modifiers or []),
        diagnosis_pointers=list(dx),
        charge=round(CHARGES[cpt] * units, 2),
    )


# --- clean archetypes ------------------------------------------------------

def clean_office_visit(rng):
    return [_line("L1", "99213")], "low", []


def clean_office_with_injection(rng):
    # E/M + procedure, modifier 25 correctly present -> clean.
    return (
        [_line("L1", "99213", modifiers=["25"]), _line("L2", "96372"), _line("L3", "J1885", units=1)],
        "neutral",
        [],
    )


def clean_lab_panel(rng):
    return (
        [_line("L1", "80053"), _line("L2", "85025"), _line("L3", "36415", units=1)],
        "neutral",
        [],
    )


def clean_cardiac(rng):
    return [_line("L1", "99213"), _line("L2", "93000")], "low", []


def clean_therapy(rng):
    u = rng.randint(1, 4)
    return [_line("L1", "97110", units=u)], "neutral", []


def clean_therapy_combo_with_59(rng):
    # 97110 + 97140 together but modifier 59 present -> clean (override).
    return (
        [_line("L1", "97110", units=2), _line("L2", "97140", units=2, modifiers=["59"])],
        "neutral",
        [],
    )


def clean_ortho(rng):
    return (
        [_line("L1", "99213", modifiers=["25"]), _line("L2", "20610", units=1)],
        "neutral",
        [],
    )


# --- true-negative distractors (look tempting, are actually clean) ---------

def distractor_high_em_supported(rng):
    # 99215 WITH supporting documentation -> engine must NOT flag it.
    return [_line("L1", "99215")], "high", []


def distractor_moderate_em_supported(rng):
    return [_line("L1", "99214")], "moderate", []


def distractor_units_at_limit(rng):
    # exactly at the MUE ceiling -> clean.
    return [_line("L1", "97110", units=4)], "neutral", []


CLEAN_BUILDERS = [
    clean_office_visit,
    clean_office_with_injection,
    clean_lab_panel,
    clean_cardiac,
    clean_therapy,
    clean_therapy_combo_with_59,
    clean_ortho,
    distractor_high_em_supported,
    distractor_moderate_em_supported,
    distractor_units_at_limit,
]


# --- defective builders (exactly one defect each) --------------------------

def defect_unbundling_lab(rng):  # R001
    return (
        [_line("L1", "80053"), _line("L2", "80048"), _line("L3", "85025")],
        "neutral",
        [("R001", ["L1", "L2"])],
    )


def defect_unbundling_ekg(rng):  # R002
    return [_line("L1", "93000"), _line("L2", "93005")], "neutral", [("R002", ["L1", "L2"])]


def defect_unbundling_therapy(rng):  # R004
    return (
        [_line("L1", "97110", units=2), _line("L2", "97140", units=2)],
        "neutral",
        [("R004", ["L1", "L2"])],
    )


def defect_unbundling_injection(rng):  # R013 (no E/M -> avoids R010)
    return (
        [_line("L1", "20610", units=1), _line("L2", "96372", units=1)],
        "neutral",
        [("R013", ["L1", "L2"])],
    )


def defect_upcoding_high(rng):  # R011
    return [_line("L1", "99215")], "under_high", [("R011", ["L1"])]


def defect_upcoding_moderate(rng):  # R012
    return [_line("L1", "99214")], "under_moderate", [("R012", ["L1"])]


def defect_duplicate(rng):  # R009
    return (
        [_line("L1", "96372", units=1), _line("L2", "96372", units=1)],
        "neutral",
        [("R009", ["L1", "L2"])],
    )


def defect_units_therapy(rng):  # R005
    return [_line("L1", "97110", units=rng.randint(5, 8))], "neutral", [("R005", ["L1"])]


def defect_units_drug(rng):  # R007
    return [_line("L1", "J1885", units=rng.randint(3, 5))], "neutral", [("R007", ["L1"])]


def defect_units_arthro(rng):  # R014
    return [_line("L1", "20610", units=rng.randint(3, 4))], "neutral", [("R014", ["L1"])]


def defect_missing_modifier(rng):  # R010 (E/M + procedure, no mod 25)
    return (
        [_line("L1", "99213"), _line("L2", "96372", units=1)],
        "low",
        [("R010", ["L1"])],
    )


# category -> builders
DEFECT_BUILDERS = {
    "unbundling": [
        defect_unbundling_lab,
        defect_unbundling_ekg,
        defect_unbundling_therapy,
        defect_unbundling_injection,
    ],
    "upcoding": [defect_upcoding_high, defect_upcoding_moderate],
    "duplicate": [defect_duplicate],
    "units_exceeded": [defect_units_therapy, defect_units_drug, defect_units_arthro],
    "missing_modifier": [defect_missing_modifier],
}

# 40 defect slots, evenly distributed across the five categories.
DEFECT_SCHEDULE = (
    ["unbundling"] * 10
    + ["upcoding"] * 8
    + ["duplicate"] * 7
    + ["units_exceeded"] * 9
    + ["missing_modifier"] * 6
)
assert len(DEFECT_SCHEDULE) == N_DEFECTIVE


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _make_patient(rng) -> Patient:
    pid = f"PT-{rng.randint(1, 60):04d}"  # pool of 60 -> repeats enable history
    return Patient(
        patient_id=pid,
        year_of_birth=rng.randint(1945, 2010),
        sex=rng.choice(["F", "M"]),
    )


def _make_provider(rng, prefer=None) -> Provider:
    npi, name, spec = prefer or rng.choice(PROVIDERS)
    return Provider(npi=npi, name=name, specialty=spec)


def _build_claim(rng, idx: int, defect_category: str | None) -> tuple[Claim, list[dict]]:
    if defect_category is None:
        builder = rng.choice(CLEAN_BUILDERS)
    else:
        builder = rng.choice(DEFECT_BUILDERS[defect_category])

    lines, note_kind, intended = builder(rng)
    claim = Claim(
        claim_id=f"CLM-{idx + 1:05d}",
        patient=_make_patient(rng),
        provider=_make_provider(rng),
        date_of_service=f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
        diagnoses=rng.sample(DIAGNOSES, k=rng.randint(1, 2)),
        lines=lines,
        provider_notes=_note(rng, note_kind),
    )
    return claim, intended


def _intended_to_findings(claim: Claim, intended, ruleset: RuleSet) -> list[Finding]:
    findings = []
    for rule_id, line_refs in intended:
        rule = ruleset.by_id(rule_id)
        assert rule is not None, f"schedule references unknown rule {rule_id}"
        findings.append(
            Finding(
                claim_id=claim.claim_id,
                rule_id=rule_id,
                defect_type=rule.defect_type,
                line_refs=sorted(line_refs),
                severity=rule.severity,
                rationale="injected defect (ground truth)",
            )
        )
    return findings


def _finding_key(f: Finding) -> tuple:
    return (f.rule_id, tuple(sorted(f.line_refs)))


def generate(seed: int = SEED) -> dict:
    """Generate the full dataset and self-verify it against the engine."""
    rng = random.Random(seed)
    ruleset = load_rules()
    engine = RuleEngine(ruleset)

    # Decide which claim indices are defective and their category.
    defect_slots = rng.sample(range(N_CLAIMS), k=N_DEFECTIVE)
    slot_to_category = {}
    schedule = list(DEFECT_SCHEDULE)
    rng.shuffle(schedule)
    for slot, cat in zip(sorted(defect_slots), schedule, strict=False):
        slot_to_category[slot] = cat

    claims: list[Claim] = []
    ground_truth: dict[str, list[Finding]] = {}
    for idx in range(N_CLAIMS):
        category = slot_to_category.get(idx)
        claim, intended = _build_claim(rng, idx, category)
        claims.append(claim)
        ground_truth[claim.claim_id] = _intended_to_findings(claim, intended, ruleset)

    # --- Self-verification: engine findings must equal injected labels -----
    mismatches = []
    for claim in claims:
        engine_findings = engine.evaluate(claim)
        engine_keys = {_finding_key(f) for f in engine_findings}
        gt_keys = {_finding_key(f) for f in ground_truth[claim.claim_id]}
        if engine_keys != gt_keys:
            mismatches.append(
                {
                    "claim_id": claim.claim_id,
                    "engine": sorted(map(str, engine_keys)),
                    "ground_truth": sorted(map(str, gt_keys)),
                }
            )
    if mismatches:
        raise AssertionError(
            "Generator/engine disagreement on "
            f"{len(mismatches)} claims (data is not clean-by-construction):\n"
            + json.dumps(mismatches[:5], indent=2)
        )

    # --- Holdout: 3 defective per category (15) + 10 clean = 25 ------------
    holdout_ids: list[str] = []
    by_category: dict[str, list[str]] = {c: [] for c in DEFECT_BUILDERS}
    clean_ids: list[str] = []
    for idx in range(N_CLAIMS):
        cid = f"CLM-{idx + 1:05d}"
        cat = slot_to_category.get(idx)
        if cat is None:
            clean_ids.append(cid)
        else:
            by_category[cat].append(cid)
    for cat in sorted(by_category):
        holdout_ids.extend(sorted(by_category[cat])[:3])
    holdout_ids.extend(clean_ids[:HOLDOUT_SIZE - len(holdout_ids)])
    holdout_ids = sorted(set(holdout_ids))

    return {
        "seed": seed,
        "claims": claims,
        "ground_truth": ground_truth,
        "holdout_ids": holdout_ids,
        "slot_to_category": {f"CLM-{s + 1:05d}": c for s, c in slot_to_category.items()},
    }


def _serialize_findings(findings: list[Finding]) -> list[dict]:
    return [f.model_dump(mode="json") for f in findings]


def write_dataset(seed: int = SEED, out_dir: Path = DATA_DIR) -> dict:
    ds = generate(seed)
    claims: list[Claim] = ds["claims"]
    gt: dict[str, list[Finding]] = ds["ground_truth"]
    holdout_ids: list[str] = ds["holdout_ids"]

    claims_json = [c.model_dump(mode="json") for c in claims]
    gt_json = {cid: _serialize_findings(fs) for cid, fs in gt.items()}

    (out_dir / "claims.json").write_text(
        json.dumps(claims_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "ground_truth.json").write_text(
        json.dumps(gt_json, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    holdout = {
        "seed": seed,
        "claim_ids": holdout_ids,
        "claims": [c.model_dump(mode="json") for c in claims if c.claim_id in holdout_ids],
        "ground_truth": {cid: gt_json[cid] for cid in holdout_ids},
    }
    (out_dir / "holdout.json").write_text(
        json.dumps(holdout, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    defective = [cid for cid, fs in gt.items() if fs]
    category_counts: dict[str, int] = {}
    for _cid, cat in ds["slot_to_category"].items():
        category_counts[cat] = category_counts.get(cat, 0) + 1
    holdout_defective = [cid for cid in holdout_ids if gt_json[cid]]
    manifest = {
        "seed": seed,
        "n_claims": len(claims),
        "n_defective": len(defective),
        "n_clean": len(claims) - len(defective),
        "total_ground_truth_findings": sum(len(fs) for fs in gt.values()),
        "defect_category_counts": dict(sorted(category_counts.items())),
        "holdout_size": len(holdout_ids),
        "holdout_defective": len(holdout_defective),
        "holdout_clean": len(holdout_ids) - len(holdout_defective),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic claims dataset.")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    manifest = write_dataset(seed=args.seed)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
