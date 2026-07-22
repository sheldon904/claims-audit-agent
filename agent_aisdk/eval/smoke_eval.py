"""Offline smoke eval for the Vercel AI SDK arm (CI, no API key, no spend).

Runs the TypeScript CLI in `--mock` (oracle) mode over a small FIXED subset of
the frozen holdout, scores it with the canonical harness, and asserts the same
metric thresholds the deterministic gate uses. This proves the whole pipeline
end-to-end — the Node tool loop, structural validation, the findings JSON the
harness consumes, and the Python scoring — is wired correctly, deterministically,
for free on every push. It is NOT a claim about model accuracy (the oracle
replays committed labels); the real numbers come from the live OpenRouter run.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from run_eval import _build_arm_result, _run_cli  # sibling module (same dir)

SUBSET_LIMIT = 8  # first 8 holdout claims — a fixed, deterministic slice.

THRESHOLDS = {
    "precision": 1.0,
    "recall": 1.0,
    "citation_validity": 1.0,
    "fabrication_rate_max": 0.0,
}


def main() -> int:
    args = SimpleNamespace(
        dataset="holdout",
        claims=None,
        limit=SUBSET_LIMIT,
        thinking="off",
        provider="auto",
        model=None,
        mock=True,
        timeout_ms=None,
        max_steps=None,
    )
    envelope = _run_cli(args)
    result = _build_arm_result(envelope, "holdout")
    assert result.metrics is not None
    m = result.metrics.as_dict()

    print("AI SDK smoke eval — oracle model on a fixed holdout subset")
    for k in ("precision", "recall", "f1", "citation_validity", "fabrication_rate",
              "true_positives", "false_positives", "false_negatives"):
        print(f"  {k:20s} {m[k]}")

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

    if failures:
        print("SMOKE EVAL FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SMOKE EVAL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
