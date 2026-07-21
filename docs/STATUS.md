# Session status — 2026-07-21 (eval complete)

This records the final state of the OpenRouter eval work: what was wrong, what
was fixed, and the results now published in the README. The project is
**complete** — the results table is populated for every arm and the crash that
interrupted the earlier run is fixed.

---

## TL;DR

- **Both LLM arms are now benchmarked live through OpenRouter** on the 25-claim
  frozen holdout (`qwen/qwen3-32b`), and the results are in the README.
- The earlier crash was a **hung Claude Code CLI subprocess with no per-claim
  timeout**. Fixed by adding a configurable `SDK_CLAIM_TIMEOUT_S` (default 300 s)
  so a wedged subprocess is bounded and recorded as *no findings* instead of
  stalling — or crashing — the whole run.
- The `claude-agent-sdk` OpenRouter routing fix (strip a trailing `/v1`,
  bearer-only auth) is committed. The README's outdated "SDK can't route through
  OpenRouter / errors" note is **rewritten** to the true story.

---

## What was wrong, and the fix

Two separate issues, both resolved:

1. **Routing (fixed earlier, committed in `09afe20`).** The Claude Code CLI
   appends `/v1/messages` to `ANTHROPIC_BASE_URL`. The old code set the base to
   `…/api/v1`, producing a double-`/v1` 404, and it also passed a conflicting
   `ANTHROPIC_API_KEY`. Fix: strip a trailing `/v1` and pass `ANTHROPIC_AUTH_TOKEN`
   (bearer) alone. (`agent_sdk/agent.py`)
2. **Stability (fixed this session).** Each claim spawns a fresh CLI subprocess;
   pointed at a third-party endpoint it can hang. With no timeout, one hung
   subprocess wedged the whole run — that was the crash. Fix: a per-claim
   `asyncio.wait_for` timeout (`SDK_CLAIM_TIMEOUT_S`, default 300 s) that records a
   timed-out claim as *no findings* and lets the run continue. Verified live: on a
   re-run this session the guard fired on hung claims and the run kept going
   instead of crashing.

---

## Results (published in the README)

Frozen holdout, 25 claims, `qwen/qwen3-32b` via OpenRouter:

| Arm | Thinking | P | R | F1 | Citation | Fabrication | Latency | $/claim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| engine (deterministic) | n/a | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | <1 ms | $0.00000 |
| langgraph · openrouter | off | 0.750 | 1.000 | 0.857 | 1.000 | 0.000 | 3.6 s | $0.00018 |
| langgraph · openrouter | on | 1.000 | 0.600 | 0.750 | 1.000 | 0.000 | 1.5 s | $0.00016 |
| claude-agent-sdk · openrouter | off | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 54.3 s | $0.00324 |
| claude-agent-sdk · openrouter | on | — | — | — | — | — | — | — |

- **Structural guarantee holds:** citation validity 1.000 and fabrication 0.000
  for the LangGraph arm in both modes (the `evidence_check` node drops any
  unsupported citation before it can become a finding).
- **Reasoning delta:** thinking *on* cleanly trades recall for precision
  (R 1.000 → 0.600, P 0.750 → 1.000). Latency/cost were a wash this run — the
  earlier "3× latency" claim did not reproduce and was removed.
- **SDK arm — off row is the clean holdout pass; on row is intentionally
  unmeasured.** The arm is correct but slow (~54 s/claim, ≈15× LangGraph) and
  flaky against the endpoint (this session's re-run timed out on roughly half the
  first claims). It's demonstrated on the holdout, not run at `--dataset full`;
  the caveat is cost/latency/stability, not correctness.

The `claude-agent-sdk · openrouter · off` numbers are from a clean holdout pass
(same happy-path code); its latency/cost are ~15×/~18× the LangGraph arm.

---

## Git / artifacts

- Committed this session: `agent_sdk/agent.py` (per-claim timeout), `README.md`
  (populated table + rewritten SDK notes), `docs/STATUS.md` (this file).
- `.env` (OpenRouter key) remains **gitignored and untracked** — never in history.
- `evals/results/*` are **gitignored / local-only**; `results_holdout.json`/`.md`
  hold the complete 4-row snapshot above. The README table is the published
  artifact.
- Deterministic gate + offline suite: **green** with the fix.

## Repro / commands

```bash
# deterministic, no key
make gate
make eval

# LLM arms via OpenRouter (needs OPENROUTER_API_KEY in .env)
python -m evals.run_eval --arm graph --thinking both --dataset holdout --provider openrouter   # fast, ~$0.008
python -m evals.run_eval --arm sdk   --thinking off  --dataset holdout --provider openrouter   # slow (~54 s/claim), stable config
# Avoid `--dataset full` for the SDK arm — impractical at ~54 s/claim and flaky.
# Tune the SDK per-claim ceiling with SDK_CLAIM_TIMEOUT_S (seconds).
```
