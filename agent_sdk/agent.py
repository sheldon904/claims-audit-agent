"""Agent v1 — claims auditor on the Claude Agent SDK.

An autonomous tool loop: the model is given the four audit tools as an in-process
MCP server and drives itself, calling ``fetch_claim`` / ``lookup_rule`` /
``check_patient_history`` to gather evidence and ``emit_finding`` (validated
against the ``Finding`` JSON Schema) to report each defect. Orchestration is the
model's job here; contrast ``agent_graph`` where it is an explicit graph.

Requires the optional ``sdk`` extra (``pip install -e ".[sdk]"``), the Claude
Code CLI on PATH, and ``ANTHROPIC_API_KEY``. The class raises a clear error if
the SDK is missing so the light-weight core/CI path never imports it.
"""

from __future__ import annotations

import asyncio
import json
import sys

from claims_audit.models import Claim, Finding
from claims_audit.prompting import SYSTEM_PROMPT, audit_task_prompt
from claims_audit.rules import RuleSet, load_rules
from claims_audit.tools import ToolContext, check_patient_history, fetch_claim, lookup_rule
from evals.harness import Usage

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TURNS = 12
DEFAULT_THINKING_TOKENS = 4000


def _text_result(payload: dict) -> dict:
    """Wrap a JSON payload in the SDK tool-result content shape."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


class ClaudeSDKAuditAgent:
    """AuditAgent implemented on claude-agent-sdk."""

    def __init__(
        self,
        claims: list[Claim],
        ruleset: RuleSet | None = None,
        model: str = DEFAULT_MODEL,
        thinking: bool = False,
        max_turns: int = DEFAULT_MAX_TURNS,
        provider: str | None = None,
    ):
        self.ruleset = ruleset or load_rules()
        self.ctx = ToolContext.build(claims, self.ruleset)
        # Resolve provider so the CLI can be pointed at OpenRouter's
        # Anthropic-compatible endpoint (experimental) via env passthrough.
        from providers.chat import build_config

        self._cfg = build_config(model=model, thinking=thinking, provider=provider)
        self.provider = self._cfg.provider
        self.model = self._cfg.model
        self.thinking = thinking
        self.max_turns = max_turns
        self.name = "claude-agent-sdk"
        self._usage = Usage()

    # ---- harness interface ------------------------------------------------

    def audit(self, claim: Claim) -> list[Finding]:
        # A single failed claim yields no findings rather than crashing a long
        # multi-claim run (the CLI spawns a subprocess per claim and can flake).
        try:
            return asyncio.run(self._audit_async(claim))
        except Exception as exc:  # noqa: BLE001 - resilience over strictness here
            print(f"[claude-agent-sdk] claim {claim.claim_id} errored: {exc}", file=sys.stderr)
            return []

    def usage(self) -> Usage:
        return Usage(self._usage.input_tokens, self._usage.output_tokens)

    # ---- SDK plumbing -----------------------------------------------------

    def _build_server(self):
        from claude_agent_sdk import create_sdk_mcp_server, tool

        ctx = self.ctx

        @tool("fetch_claim", "Fetch a full claim record by id.", {"claim_id": str})
        async def _fetch(args):
            return _text_result(fetch_claim(ctx, args["claim_id"]))

        @tool(
            "lookup_rule",
            "Look up rules by rule_id, by CPT code, or all rules if neither is given.",
            {"rule_id": str, "code": str},
        )
        async def _lookup(args):
            return _text_result(
                lookup_rule(ctx, rule_id=args.get("rule_id"), code=args.get("code"))
            )

        @tool(
            "check_patient_history",
            "Return the patient's other claims for cross-claim checks.",
            {"patient_id": str, "exclude_claim_id": str},
        )
        async def _history(args):
            return _text_result(
                check_patient_history(
                    ctx, args["patient_id"], args.get("exclude_claim_id")
                )
            )

        @tool(
            "emit_finding",
            "Emit one validated audit finding citing rule_id and line_refs.",
            {
                "claim_id": str,
                "rule_id": str,
                "defect_type": str,
                "line_refs": list,
                "severity": str,
                "rationale": str,
            },
        )
        async def _emit(args):
            payload = {
                "claim_id": args.get("claim_id"),
                "rule_id": args.get("rule_id"),
                "defect_type": args.get("defect_type"),
                "line_refs": args.get("line_refs") or [],
                "severity": args.get("severity") or "medium",
                "rationale": args.get("rationale") or "",
            }
            try:
                model = Finding.model_validate(payload)
            except Exception as exc:  # noqa: BLE001 - surface validation to model
                return {
                    "content": [{"type": "text", "text": f"REJECTED: {exc}"}],
                    "is_error": True,
                }
            ctx.emitted.append(model)
            return _text_result({"accepted": True})

        return create_sdk_mcp_server(
            name="audit", tools=[_fetch, _lookup, _history, _emit]
        )

    def _options(self, server):
        from claude_agent_sdk import ClaudeAgentOptions

        kwargs = dict(
            mcp_servers={"audit": server},
            allowed_tools=[
                "mcp__audit__fetch_claim",
                "mcp__audit__lookup_rule",
                "mcp__audit__check_patient_history",
                "mcp__audit__emit_finding",
            ],
            system_prompt=SYSTEM_PROMPT,
            model=self.model,
            max_turns=self.max_turns,
            # tools must be used offline: no filesystem / network side effects.
            setting_sources=None,
        )
        if self.thinking:
            kwargs["max_thinking_tokens"] = DEFAULT_THINKING_TOKENS

        # OpenRouter routing: point the Claude Code CLI at OpenRouter's
        # Anthropic-compatible endpoint. The CLI appends "/v1/messages" to
        # ANTHROPIC_BASE_URL, so the base must NOT already end in /v1 — OpenRouter
        # serves it at https://openrouter.ai/api/v1/messages. Auth is a bearer
        # token (ANTHROPIC_AUTH_TOKEN), which is what OpenRouter expects.
        if self.provider == "openrouter" and self._cfg.api_key:
            base = (self._cfg.base_url or "https://openrouter.ai/api/v1").rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3].rstrip("/")
            kwargs["env"] = {
                "ANTHROPIC_BASE_URL": base,
                "ANTHROPIC_AUTH_TOKEN": self._cfg.api_key,
            }
        return ClaudeAgentOptions(**kwargs)

    async def _audit_async(self, claim: Claim) -> list[Finding]:
        from claude_agent_sdk import ResultMessage, query

        self.ctx.reset_emitted()
        server = self._build_server()
        options = self._options(server)
        prompt = audit_task_prompt(claim, self.ruleset)

        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage) and message.usage:
                u = message.usage
                self._usage = Usage(
                    self._usage.input_tokens + int(u.get("input_tokens", 0)),
                    self._usage.output_tokens + int(u.get("output_tokens", 0)),
                )
        # Only findings about THIS claim (guard against stray tool calls).
        return [f for f in self.ctx.emitted if f.claim_id == claim.claim_id]
