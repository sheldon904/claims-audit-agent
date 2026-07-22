import { MockLanguageModelV4 } from 'ai/test';
import { describe, expect, it } from 'vitest';
import { auditClaim } from '../src/agent.js';
import { AuditContext } from '../src/context.js';
import type { Claim } from '../src/models.js';
import { buildOracleModel } from '../src/mock.js';
import type { ProviderConfig } from '../src/provider.js';
import { loadRules } from '../src/rules.js';

const RS = loadRules();

const CFG: ProviderConfig = {
  provider: 'openrouter',
  model: 'qwen/qwen3-32b',
  thinking: false,
  apiKey: undefined,
  baseURL: undefined,
  maxTokens: 8000,
  thinkingTokens: 4000,
};

function ncciClaim(): Claim {
  return {
    claim_id: 'CLM-X',
    patient: { patient_id: 'PT-1', year_of_birth: 1980, sex: 'F' },
    provider: { npi: '1013001112', name: 'Cedar', specialty: 'family_medicine' },
    date_of_service: '2025-03-01',
    diagnoses: ['I10'],
    lines: [
      { line_id: 'L1', cpt: '80053', units: 1, modifiers: [], diagnosis_pointers: [], charge: 38 },
      { line_id: 'L2', cpt: '80048', units: 1, modifiers: [], diagnosis_pointers: [], charge: 24 },
    ],
    provider_notes: 'labs drawn',
  };
}

describe('agent loop', () => {
  it('runs end-to-end via the tool loop and records what the model emits', async () => {
    const claim = ncciClaim();
    const ctx = AuditContext.build([claim], RS);
    // One real finding + one hallucinated rule + one hallucinated line. Unlike
    // the LangGraph arm (which prunes), this autonomous arm records all three;
    // the fabrication metric is what flags the bad two downstream.
    const model = buildOracleModel([
      { claim_id: 'CLM-X', rule_id: 'R001', defect_type: 'unbundling', line_refs: ['L1', 'L2'] },
      { claim_id: 'CLM-X', rule_id: 'R999', defect_type: 'unbundling', line_refs: ['L1'] },
      { claim_id: 'CLM-X', rule_id: 'R001', defect_type: 'unbundling', line_refs: ['L9'] },
    ]);
    const r = await auditClaim(ctx, 'CLM-X', model, { cfg: CFG });
    expect(r.error).toBeUndefined();
    expect(r.findings).toHaveLength(3);
    expect(r.findings.map((f) => f.rule_id).sort()).toEqual(['R001', 'R001', 'R999']);
  });

  it('a clean claim (oracle emits nothing) yields no findings', async () => {
    const claim = ncciClaim();
    const ctx = AuditContext.build([claim], RS);
    const r = await auditClaim(ctx, 'CLM-X', buildOracleModel([]), { cfg: CFG });
    expect(r.findings).toHaveLength(0);
  });

  it('the loop is bounded by stepCountIs even if the model never stops', async () => {
    const claim = ncciClaim();
    const ctx = AuditContext.build([claim], RS);
    // A runaway model that calls lookup_rule forever. Without a bound this would
    // never terminate; stopWhen: stepCountIs(maxSteps) must halt it.
    const runaway = new MockLanguageModelV4({
      doGenerate: () =>
        Promise.resolve({
          content: [
            {
              type: 'tool-call' as const,
              toolCallId: 'loop',
              toolName: 'lookup_rule',
              input: JSON.stringify({}),
            },
          ],
          finishReason: { unified: 'tool-calls' as const, raw: undefined },
          usage: {
            inputTokens: { total: 5, noCache: 5, cacheRead: undefined, cacheWrite: undefined },
            outputTokens: { total: 5, text: 5, reasoning: undefined },
          },
          warnings: [],
        }),
    });
    const r = await auditClaim(ctx, 'CLM-X', runaway, { cfg: CFG, maxSteps: 3 });
    expect(r.error).toBeUndefined();
    expect(r.findings).toHaveLength(0);
    expect(r.steps).toBeLessThanOrEqual(3);
    expect(r.steps).toBeGreaterThan(0);
  });
});
