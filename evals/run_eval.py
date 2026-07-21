"""Eval runner CLI.

Examples
--------
    # deterministic baseline on the frozen holdout (no API key needed)
    python -m evals.run_eval --arm engine

    # both LLM arms, extended thinking on/off, via OpenRouter
    OPENROUTER_API_KEY=sk-or-... \\
      python -m evals.run_eval --arm sdk --arm graph --thinking both --provider openrouter

    # native Anthropic instead
    ANTHROPIC_API_KEY=sk-... python -m evals.run_eval --arm graph --provider anthropic

Results are printed as a Markdown table and written to ``evals/results/``.
The ``engine`` arm is fully reproducible; the ``sdk``/``graph`` arms require the
relevant optional extra plus credentials for the chosen provider. A ``.env`` file
in the repo root is auto-loaded when ``python-dotenv`` is installed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from claims_audit.models import Claim, Finding
from claims_audit.rules import load_rules
from evals.baseline import EngineAgent
from evals.harness import ArmResult, load_full, load_holdout, run_arm
from evals.reporting import DEFAULT_MODEL, arm_row, render_markdown_table, save_results
from providers.chat import resolve_provider

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_dotenv() -> None:
    """Load a repo-root .env if python-dotenv is available (no-op otherwise)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _provider_key_present(provider: str) -> bool:
    if provider == "openrouter":
        return bool(os.getenv("OPENROUTER_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _load_dataset(name: str) -> tuple[list[Claim], dict[str, list[Finding]]]:
    return load_full() if name == "full" else load_holdout()


def _build_llm_arm(arm: str, claims, ruleset, thinking: bool, model: str, provider: str):
    """Construct an LLM arm and its usage accessor; raise a clear error if unavailable."""
    if arm == "sdk":
        from agent_sdk.agent import ClaudeSDKAuditAgent

        agent = ClaudeSDKAuditAgent(
            claims, ruleset=ruleset, model=model, thinking=thinking, provider=provider
        )
    elif arm == "graph":
        from agent_graph.graph import LangGraphAuditAgent

        agent = LangGraphAuditAgent(
            claims, ruleset=ruleset, model_name=model, thinking=thinking, provider=provider
        )
    else:
        raise ValueError(f"unknown arm {arm!r}")
    return agent, (lambda a: a.usage())


def run_one(
    arm: str,
    thinking: bool,
    dataset: str,
    model: str,
    limit: int | None,
    provider: str,
) -> ArmResult:
    ruleset = load_rules()
    claims, gt = _load_dataset(dataset)
    if limit:
        claims = claims[:limit]
        # Subset ground truth to the evaluated claims so a limited smoke run
        # doesn't count the dropped claims' defects as false negatives.
        gt = {c.claim_id: gt.get(c.claim_id, []) for c in claims}

    if arm == "engine":
        agent = EngineAgent(ruleset)
        result = run_arm(agent, claims, gt, ruleset, config={"sdk": "engine (deterministic)"})
        return result

    agent, usage_of = _build_llm_arm(arm, claims, ruleset, thinking, model, provider)
    config = {
        "sdk": {"sdk": "claude-agent-sdk", "graph": "langgraph"}[arm],
        "provider": getattr(agent, "provider", provider),
        "thinking": "on" if thinking else "off",
        "model": getattr(agent, "model", None) or model,
    }
    return run_arm(agent, claims, gt, ruleset, config=config, usage_of=usage_of)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arm",
        action="append",
        choices=["engine", "sdk", "graph"],
        help="Arm(s) to evaluate. Repeatable. Default: engine.",
    )
    parser.add_argument("--thinking", choices=["on", "off", "both"], default="off")
    parser.add_argument("--dataset", choices=["holdout", "full"], default="holdout")
    parser.add_argument(
        "--provider",
        choices=["auto", "anthropic", "openrouter"],
        default="auto",
        help="LLM backend. 'auto' picks openrouter if OPENROUTER_API_KEY is set.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None, help="Path to write results JSON.")
    args = parser.parse_args(argv)

    _load_dotenv()
    provider = resolve_provider(args.provider)

    arms = args.arm or ["engine"]
    thinking_modes = (
        [False, True] if args.thinking == "both" else [args.thinking == "on"]
    )

    rows = []
    arm_results: list[ArmResult] = []
    for arm in arms:
        modes = thinking_modes if arm != "engine" else [False]
        for thinking in modes:
            if arm in ("sdk", "graph") and not _provider_key_present(provider):
                key = "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
                print(
                    f"[skip] arm={arm} thinking={'on' if thinking else 'off'} "
                    f"provider={provider}: {key} not set.",
                    file=sys.stderr,
                )
                continue
            try:
                result = run_one(
                    arm, thinking, args.dataset, args.model, args.limit, provider
                )
            except ImportError as exc:
                print(f"[skip] arm={arm}: optional dependency missing ({exc}).", file=sys.stderr)
                continue
            arm_results.append(result)
            rows.append(arm_row(result))

    if not rows:
        print("No arms ran. Try --arm engine (no API key required).", file=sys.stderr)
        return 1

    table = render_markdown_table(rows)
    print(f"\nDataset: {args.dataset}   Claims: {args.limit or 'all'}\n")
    print(table)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"results_{args.dataset}.json"
    save_results(rows, out_path)
    (RESULTS_DIR / f"results_{args.dataset}.md").write_text(table + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
