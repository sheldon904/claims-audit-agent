/**
 * Agent v3 — the same auditor on the Vercel AI SDK.
 *
 * Like `agent_sdk` (and unlike the `agent_graph` fixed graph), the model drives
 * an autonomous tool loop: it is handed the four tools and calls `fetch_claim` /
 * `lookup_rule` / `check_patient_history` to gather evidence and `emit_finding`
 * per defect. Control flow lives in the model; the loop is bounded by
 * `stopWhen: stepCountIs(maxSteps)`. This deliberately mirrors the autonomous
 * `claude-agent-sdk` arm rather than the LangGraph arm, so the three-way
 * comparison contrasts genuinely different orchestration styles.
 */
import { type LanguageModel, type ToolSet, generateText, stepCountIs } from 'ai';
import type { AuditContext } from './context.js';
import type { Finding } from './models.js';
import { auditTaskPrompt, SYSTEM_PROMPT } from './prompting.js';
import { type ProviderConfig, providerOptions } from './provider.js';
import { buildTools } from './tools.js';

export const DEFAULT_MAX_STEPS = 12;

export interface ClaimUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ClaimAuditResult {
  claim_id: string;
  findings: Finding[];
  usage: ClaimUsage;
  latency_ms: number;
  steps: number;
  error?: string;
}

export interface AuditOptions {
  cfg: ProviderConfig;
  maxSteps?: number;
  /** Per-claim wall-clock ceiling; a wedged call becomes "no findings". */
  timeoutMs?: number | undefined;
  /**
   * Extra tools (e.g. discovered from an external MCP server) exposed to the
   * model alongside the four audit tools. Not used by the scored benchmark —
   * present so an MCP-sourced tool can be genuinely reachable by the agent.
   */
  extraTools?: ToolSet | undefined;
}

/**
 * Audit one claim. Never throws: a model/transport failure (or a per-claim
 * timeout) is recorded as zero findings with an `error` note, so one bad claim
 * cannot crash a multi-claim run — the same resilience the `claude-agent-sdk`
 * arm applies with its per-claim timeout.
 */
export async function auditClaim(
  ctx: AuditContext,
  claimId: string,
  model: LanguageModel,
  opts: AuditOptions,
): Promise<ClaimAuditResult> {
  ctx.resetEmitted();
  ctx.currentClaimId = claimId;

  const claim = ctx.claims.get(claimId);
  const start = performance.now();
  if (claim === undefined) {
    return {
      claim_id: claimId,
      findings: [],
      usage: { input_tokens: 0, output_tokens: 0 },
      latency_ms: performance.now() - start,
      steps: 0,
      error: `claim ${claimId} not found`,
    };
  }

  const po = providerOptions(opts.cfg);
  try {
    const result = await generateText({
      model,
      system: SYSTEM_PROMPT,
      prompt: auditTaskPrompt(claim, ctx.ruleset),
      tools: { ...buildTools(ctx), ...(opts.extraTools ?? {}) },
      maxOutputTokens: opts.cfg.maxTokens,
      stopWhen: stepCountIs(opts.maxSteps ?? DEFAULT_MAX_STEPS),
      ...(po ? { providerOptions: po } : {}),
      ...(opts.timeoutMs ? { abortSignal: AbortSignal.timeout(opts.timeoutMs) } : {}),
    });
    return {
      claim_id: claimId,
      // Only findings about THIS claim (guard against a stray emit).
      findings: ctx.emitted.filter((f) => f.claim_id === claimId),
      usage: {
        input_tokens: result.usage.inputTokens ?? 0,
        output_tokens: result.usage.outputTokens ?? 0,
      },
      latency_ms: performance.now() - start,
      steps: result.steps.length,
    };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      claim_id: claimId,
      findings: ctx.emitted.filter((f) => f.claim_id === claimId),
      usage: { input_tokens: 0, output_tokens: 0 },
      latency_ms: performance.now() - start,
      steps: 0,
      error: message,
    };
  }
}
