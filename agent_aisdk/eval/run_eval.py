"""Score the Vercel AI SDK arm with the repo's CANONICAL eval harness.

This is how "run the full existing eval against the new arm" is satisfied without
touching a single line of `evals/`. The flow:

    node dist/cli.js --dataset holdout --all   ->  findings JSON (per claim)
        -> parsed into claims_audit.models.Finding
        -> claims_audit.metrics.score_dataset   (THE scoring authority, unchanged)
        -> evals.harness.ArmResult              (the same result container)
        -> evals.reporting.arm_row / render_markdown_table / cost_usd (unchanged)

Only the *execution* happens in Node; every metric, the cost model, the row shape
and the table are the canonical Python ones. Latency is measured inside the one
warm Node process (per claim), which is a fair basis of comparison with the
in-process LangGraph arm rather than a subprocess-per-claim penalty.

Usage
-----
    # offline, deterministic (oracle model, no key) — the CI smoke path uses this
    python agent_aisdk/eval/run_eval.py --dataset holdout --mock --limit 6

    # live, apples-to-apples with the other arms (qwen/qwen3-32b via OpenRouter)
    python agent_aisdk/eval/run_eval.py --dataset holdout --provider openrouter
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ARM_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ARM_DIR.parent
ARTIFACTS_DIR = ARM_DIR / "artifacts"
CLI_DIST = ARM_DIR / "dist" / "cli.js"

# Make the canonical packages importable when run by file path (the repo need
# not be pip-installed for this script to work locally).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Canonical harness + reporting — imported, never modified.
from claims_audit.metrics import score_dataset  # noqa: E402
from claims_audit.models import Finding  # noqa: E402
from claims_audit.rules import load_rules  # noqa: E402
from evals.harness import ArmResult, Usage, load_full, load_holdout  # noqa: E402
from evals.reporting import arm_row, render_markdown_table, save_results  # noqa: E402


def _resolve_cli() -> list[str]:
    """Prefer the built CLI; build it once if missing (needs `npm ci` first)."""
    node = shutil.which("node")
    if node is None:
        raise SystemExit("node not found on PATH — install Node >= 20 to run the AI SDK arm.")
    if not CLI_DIST.exists():
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit(
                "dist/cli.js missing and npm not found. Run: "
                "npm --prefix agent_aisdk ci && npm --prefix agent_aisdk run build"
            )
        print("[aisdk-eval] dist/cli.js missing — building ...", file=sys.stderr)
        subprocess.run([npm, "run", "build"], cwd=ARM_DIR, check=True)
    return [node, str(CLI_DIST)]


def _run_cli(args: argparse.Namespace) -> dict:
    cmd = _resolve_cli()
    cmd += ["--dataset", args.dataset]
    if args.claims:
        cmd += args.claims
    else:
        cmd += ["--all"]
    if args.limit is not None:
        cmd += ["--limit", str(args.limit)]
    cmd += ["--thinking", "on" if args.thinking == "on" else "off"]
    if args.mock:
        cmd += ["--mock"]
    else:
        cmd += ["--provider", args.provider]
        if args.model:
            cmd += ["--model", args.model]
    if args.timeout_ms is not None:
        cmd += ["--timeout-ms", str(args.timeout_ms)]
    if args.max_steps is not None:
        cmd += ["--max-steps", str(args.max_steps)]

    print(f"[aisdk-eval] $ {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"AI SDK CLI failed (exit {proc.returncode}).")
    sys.stderr.write(proc.stderr)
    return json.loads(proc.stdout)


def _build_arm_result(envelope: dict, dataset: str) -> ArmResult:
    claims, ground_truth = load_full() if dataset == "full" else load_holdout()
    claims_by_id = {c.claim_id: c for c in claims}
    ruleset = load_rules()

    predictions: dict[str, list[Finding]] = {}
    latencies_ms: dict[str, float] = {}
    usage: dict[str, Usage] = {}
    for row in envelope["results"]:
        cid = row["claim_id"]
        predictions[cid] = [Finding.model_validate(f) for f in row["findings"]]
        latencies_ms[cid] = float(row["latency_ms"])
        u = row.get("usage", {})
        usage[cid] = Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))

    # Subset ground truth to the evaluated claims (mirrors run_eval's --limit
    # handling) so a partial run doesn't count dropped claims as false negatives.
    gt = {cid: ground_truth.get(cid, []) for cid in predictions}

    config = {
        "sdk": "vercel-ai-sdk",
        "provider": envelope.get("provider"),
        "thinking": envelope.get("thinking", "off"),
        "model": envelope.get("model"),
    }
    result = ArmResult(
        name="vercel-ai-sdk",
        config=config,
        predictions=predictions,
        latencies_ms=latencies_ms,
        usage=usage,
    )
    result.metrics = score_dataset(predictions, gt, claims_by_id, ruleset)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["holdout", "full"], default="holdout")
    parser.add_argument("--claims", nargs="*", default=None, help="Specific claim ids (default: all).")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--thinking", choices=["on", "off"], default="off")
    parser.add_argument("--provider", choices=["auto", "anthropic", "openrouter"], default="auto")
    parser.add_argument("--model", default=None)
    parser.add_argument("--mock", action="store_true", help="Offline oracle model (no key).")
    parser.add_argument("--timeout-ms", type=int, default=None)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--out", default=None, help="Path to write results JSON.")
    args = parser.parse_args(argv)

    envelope = _run_cli(args)
    result = _build_arm_result(envelope, args.dataset)
    row = arm_row(result)
    table = render_markdown_table([row])

    print(f"\nDataset: {args.dataset}   Arm: vercel-ai-sdk   "
          f"provider={envelope.get('provider')} thinking={envelope.get('thinking')}\n")
    print(table)

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    suffix = "mock" if args.mock else f"{envelope.get('provider')}_{envelope.get('thinking')}"
    out_json = Path(args.out) if args.out else ARTIFACTS_DIR / f"results_{args.dataset}_{suffix}.json"
    save_results([row], out_json)
    (ARTIFACTS_DIR / f"results_{args.dataset}_{suffix}.md").write_text(table + "\n", encoding="utf-8")
    # Also keep the raw per-claim CLI envelope as the primary committed evidence.
    (ARTIFACTS_DIR / f"aisdk_{args.dataset}_{suffix}_raw.json").write_text(
        json.dumps(envelope, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {out_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
