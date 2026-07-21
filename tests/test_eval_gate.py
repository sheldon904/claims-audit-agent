"""The CI regression gate, as a test.

If this fails, either the rules or the frozen data drifted such that the
deterministic auditor no longer perfectly recovers the labelled defects, or a
citation became invalid. Either way the audit is no longer trustworthy and the
build must go red.
"""

from claims_audit.rules import load_rules
from evals.baseline import EngineAgent
from evals.gate import check
from evals.harness import load_full, run_arm


def test_gate_passes_on_holdout():
    ok, metrics, failures = check()
    assert ok, f"eval gate failed: {failures} (metrics={metrics})"
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["citation_validity"] == 1.0
    assert metrics["fabrication_rate"] == 0.0


def test_engine_perfect_on_full_set():
    ruleset = load_rules()
    claims, gt = load_full()
    result = run_arm(EngineAgent(ruleset), claims, gt, ruleset)
    m = result.metrics.as_dict()
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["fabrication_rate"] == 0.0
    # every ground-truth defect on the full set is recovered
    assert m["true_positives"] == m["ground_truth_count"]
