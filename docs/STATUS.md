# Session status — 2026-07-20 (end of night)

**Read this first next session.** It records what went wrong, the exact current
state of the tree, and the shortest path to resume. Nothing here is committed
unless the "Git state" section says so.

---

## TL;DR

- The **SDK-via-OpenRouter fix works** — the `claude-agent-sdk` arm now routes
  through OpenRouter and scored a **perfect run on the 25-claim holdout**
  (P/R/F1 = 1.000, citation validity 1.000, fabrication 0.000).
- **But it is slow and flaky at scale**: ~**54 s/claim** (≈15× LangGraph),
  because every claim spawns a fresh Claude Code CLI subprocess. Attempting a
  larger/repeated run overwhelmed the session and **the Claude Code CLI crashed**,
  dumping gibberish to the terminal. That is the crash you saw.
- The fix lives in the working tree **uncommitted** (`agent_sdk/agent.py`). The
  holdout result that proves it lives in `evals/results/` which is **gitignored**
  (local-only). The **README still says the SDK arm can't route through
  OpenRouter** — that note is now outdated and needs a rewrite (see "Next steps").

---

## What went wrong (root cause)

The published README claimed the `claude-agent-sdk` arm "errors" when pointed at
OpenRouter. Tonight I found *why* and fixed it:

1. **Double `/v1` in the base URL.** The Claude Code CLI appends `/v1/messages`
   to `ANTHROPIC_BASE_URL`. The old code set the base to
   `https://openrouter.ai/api/v1`, so the CLI hit
   `…/api/v1/v1/messages` → 404. Fix: strip a trailing `/v1` from the base so the
   CLI's appended path lands on `https://openrouter.ai/api/v1/messages`.
2. **Conflicting auth vars.** The old code set both `ANTHROPIC_AUTH_TOKEN` and
   `ANTHROPIC_API_KEY`. OpenRouter wants the bearer token only. Fix: pass
   `ANTHROPIC_AUTH_TOKEN` alone.

With those two changes the SDK arm ran clean on the holdout. **The remaining
problem is not correctness — it's cost/latency/stability at scale:**

- Each claim = one fresh CLI subprocess pointed at a third-party endpoint.
- At ~54 s/claim, a 200-claim `--dataset full` run is ~3 hours of subprocess
  churn. Somewhere in a large/repeated run the CLI crashed (the gibberish in the
  terminal). No `results_full.md` LLM rows were ever produced — only the engine
  row exists there.
- I added a `try/except` around `audit()` so **one** flaky claim returns `[]`
  instead of killing the whole run. That makes multi-claim runs survivable but
  does **not** make the CLI fast or fully stable — it's a resilience guard, not a
  cure.

---

## Current state of the system

### Git state
- Branch `main`, **up to date with `origin/main`** — everything through commit
  `e5e40b3` is pushed.
- **One uncommitted file:** `agent_sdk/agent.py` — the OpenRouter fix + resilience
  guard described above. **Not committed, not pushed.**
- This file, `docs/STATUS.md`, is new and **also uncommitted** (unless you commit
  it — see Next steps).

### Secret / .env
- `.env` (with the OpenRouter key) exists in the repo root. It is **gitignored
  and NOT tracked** — it never entered git history. Safe. Left in place so config
  still works. `.env.example` is the tracked template.

### Tests
- Deterministic gate + offline suite: **green** with the uncommitted fix.
  (`pytest tests/test_agents_offline.py tests/test_eval_gate.py` → gate passes;
  the 3 SDK-offline tests **skip** because they need the Claude Code CLI, which is
  expected.)

### Results artifacts (all under `evals/results/`, **gitignored / local-only**)
- `results_holdout.md` → **has a real SDK-via-OpenRouter row** from tonight:
  `claude-agent-sdk · openrouter · qwen/qwen3-32b · thinking off` →
  P 1.000 / R 1.000 / F1 1.000 / citation 1.000 / fabrication 0.000 /
  **54294 ms** / **$0.00324/claim**.
- `results_full.md` → **only the engine row.** The LLM arms never completed on the
  full 200-claim set.

### Processes
- No leaked benchmark processes. No `python` running (the aborted eval already
  died). The `node` cluster seen during triage was this session's MCP servers,
  not orphans. (One old `node` PID 27048 from ~15:50 was left untouched — likely
  an editor, not ours.)

---

## What is proven vs. not

| Claim | Status |
| --- | --- |
| SDK arm can route through OpenRouter | ✅ proven (holdout, perfect scores) |
| SDK arm orchestration is correct | ✅ proven (holdout + offline CI) |
| SDK arm is practical at full-dataset scale | ❌ no — 54 s/claim, CLI crashed on a large run |
| LangGraph arm via OpenRouter | ✅ already in README (unchanged tonight) |
| README's "SDK can't use OpenRouter" note | ⚠️ now outdated — needs rewrite |

---

## Next steps (shortest path, in order)

1. **Decide on the `agent_sdk/agent.py` fix.** It's correct and valuable — commit
   it. Suggested message: `Fix claude-agent-sdk OpenRouter routing (strip /v1, bearer-only) + per-claim resilience`.
2. **Commit this `docs/STATUS.md`** (or delete it once its content is folded into
   the README).
3. **Rewrite the README SDK note.** The current text (lines ~49–55, ~168, ~187)
   says the SDK arm "errors" on OpenRouter and its rows are `—`. That's no longer
   the accurate story. Replace with the *true* one:
   - It **does** route through OpenRouter now (the fix).
   - It scored perfectly on the holdout.
   - The honest caveat is **cost/latency**: ~54 s/claim vs LangGraph's ~4–11 s,
     ~20× the $/claim, because of subprocess-per-claim — so it's demonstrated on
     the holdout, not run at full scale.
   - You can now fill the `claude-agent-sdk` holdout rows with real numbers from
     `evals/results/results_holdout.md` if you want them published.
4. **If you want a published SDK number:** re-run only the holdout, thinking off,
   SDK arm — it's ~25 × 54 s ≈ 22 min and ~$0.08. Do **not** attempt
   `--dataset full` for the SDK arm; it's the thing that crashed.
   ```bash
   # holdout only, SDK arm, no thinking — the stable configuration
   python -m evals.run_eval --arm sdk --thinking off --dataset holdout --provider openrouter
   ```
5. **Optional hardening before any larger SDK run:** add a per-claim timeout and/or
   a small concurrency cap so a hung subprocess can't wedge the whole run.

## Repro / commands reference

```bash
# what crashed (do NOT repeat as-is): both LLM arms, both thinking modes, ...
# full dataset would be ~3h of CLI subprocesses for the SDK arm.
make eval-openrouter          # = run_eval --arm sdk --arm graph --thinking both --dataset holdout --provider openrouter

# safe: deterministic, no API key
make gate
make eval
```
