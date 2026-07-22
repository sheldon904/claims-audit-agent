/**
 * Offline oracle model — a `MockLanguageModelV4` that emits a scripted set of
 * findings through the *real* `generateText` tool loop (real tools, real
 * `emit_finding`, real JSON output). It is the TypeScript analogue of the Python
 * offline suite's scripted fake model: it lets the whole pipeline — tool loop,
 * structural validation, CLI JSON, and Python scoring — run deterministically in
 * CI with no API key and no spend.
 *
 * The oracle is an ORACLE (it can be handed the committed ground truth) purely so
 * the scored smoke row is meaningful; it is not a claim about any model's real
 * accuracy. Real numbers come from the live OpenRouter run.
 */
import { MockLanguageModelV4 } from 'ai/test';
import type { LanguageModel } from 'ai';

export interface ScriptedFinding {
  claim_id?: string;
  rule_id: string;
  defect_type: string;
  line_refs: string[];
  severity?: string;
  rationale?: string;
}

const ZERO_USAGE = {
  inputTokens: { total: 100, noCache: 100, cacheRead: undefined, cacheWrite: undefined },
  outputTokens: { total: 20, text: 20, reasoning: undefined },
} as const;

/**
 * Build a mock model that, on its first generation, emits one `emit_finding`
 * tool call per scripted finding, then stops. A clean claim (no scripted
 * findings) stops immediately with no tool calls.
 */
export function buildOracleModel(findings: ScriptedFinding[]): LanguageModel {
  let call = 0;
  return new MockLanguageModelV4({
    doGenerate: () => {
      const step = call;
      call += 1;
      if (step === 0 && findings.length > 0) {
        return Promise.resolve({
          content: findings.map((f, i) => ({
            type: 'tool-call' as const,
            toolCallId: `oracle_${i}`,
            toolName: 'emit_finding',
            input: JSON.stringify({
              claim_id: f.claim_id,
              rule_id: f.rule_id,
              defect_type: f.defect_type,
              line_refs: f.line_refs,
              severity: f.severity ?? 'medium',
              rationale: f.rationale ?? '',
            }),
          })),
          finishReason: { unified: 'tool-calls' as const, raw: undefined },
          usage: ZERO_USAGE,
          warnings: [],
        });
      }
      return Promise.resolve({
        content: [{ type: 'text' as const, text: 'done' }],
        finishReason: { unified: 'stop' as const, raw: undefined },
        usage: ZERO_USAGE,
        warnings: [],
      });
    },
  });
}
