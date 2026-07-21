"""The CI regression gate.

Runs the deterministic engine arm over the frozen holdout and fails (non-zero
exit) if any metric regresses below its threshold. This is the machine-checkable
version of "the audit still works": if a rule change or a data change breaks
detection or introduces a citation defect, CI turns red.

Thresholds are set at the deterministic engine's guaranteed performance. The
LLM arms are reported in the README but are intentionally NOT gated here, because
they are non-deterministic and cost money to run — the gate must be free and
reproducible on every push.
"""

from __future__ import annotations

import sys

from claims_audit.rules import load_rules
from evals.baseline import EngineAgent
from evals.harness import load_holdout, run_arm

# Minimum acceptable metrics for the deterministic engine on the holdout.
THRESHOLDS = {
    "precision": 1.0,
    "recall": 1.0,
    "citation_validity": 1.0,
    "fabrication_rate_max": 0.0,
}


def check() -> tuple[bool, dict, list[str]]:
    ruleset = load_rules()
    claims, gt = load_holdout()
    result = run_arm(EngineAgent(ruleset), claims, gt, ruleset)
    m = result.metrics.as_dict()

    failures = []
    if m["precision"] < THRESHOLDS["precision"]:
        failures.append(f"precision {m['precision']} < {THRESHOLDS['precision']}")
    if m["recall"] < THRESHOLDS["recall"]:
        failures.append(f"recall {m['recall']} < {THRESHOLDS['recall']}")
    if m["citation_validity"] < THRESHOLDS["citation_validity"]:
        failures.append(
            f"citation_validity {m['citation_validity']} < {THRESHOLDS['citation_validity']}"
        )
    if m["fabrication_rate"] > THRESHOLDS["fabrication_rate_max"]:
        failures.append(
            f"fabrication_rate {m['fabrication_rate']} > {THRESHOLDS['fabrication_rate_max']}"
        )
    return (not failures), m, failures


def main() -> int:
    ok, metrics, failures = check()
    print("Eval gate — deterministic engine on frozen holdout")
    for k, v in metrics.items():
        print(f"  {k:20s} {v}")
    if ok:
        print("GATE PASSED")
        return 0
    print("GATE FAILED:")
    for f in failures:
        print(f"  - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
