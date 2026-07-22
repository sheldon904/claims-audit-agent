import { beforeEach, describe, expect, it } from 'vitest';
import { AuditContext } from '../src/context.js';
import type { Claim } from '../src/models.js';
import { loadRules } from '../src/rules.js';
import { buildTools } from '../src/tools.js';

const RS = loadRules();

// The tool-execute options type is not exported by name; derive it structurally
// from the tool so the test stays honest against the real signature.
type Tools = ReturnType<typeof buildTools>;
type ExecOpts = Parameters<NonNullable<Tools['fetch_claim']['execute']>>[1];
// The tools ignore their execution options; a minimal stub is fine for unit
// tests (double-cast keeps it a properly-typed value, no `any`).
const TOOL_OPTS = { toolCallId: 't', messages: [] } as unknown as ExecOpts;

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

function priorClaim(): Claim {
  return {
    claim_id: 'CLM-Y',
    patient: { patient_id: 'PT-1', year_of_birth: 1980, sex: 'F' },
    provider: { npi: '1013001112', name: 'Cedar', specialty: 'family_medicine' },
    date_of_service: '2025-01-01',
    diagnoses: ['I10'],
    lines: [
      { line_id: 'L1', cpt: '36415', units: 1, modifiers: [], diagnosis_pointers: [], charge: 10 },
    ],
    provider_notes: '',
  };
}

describe('the four tools are faithful ports of the shared core', () => {
  let ctx: AuditContext;
  let tools: ReturnType<typeof buildTools>;

  beforeEach(() => {
    ctx = AuditContext.build([ncciClaim(), priorClaim()], RS);
    ctx.currentClaimId = 'CLM-X';
    tools = buildTools(ctx);
  });

  it('fetch_claim returns the record, or an error for a missing id', async () => {
    const ok = await tools.fetch_claim.execute({ claim_id: 'CLM-X' }, TOOL_OPTS);
    expect((ok as Claim).claim_id).toBe('CLM-X');
    const miss = await tools.fetch_claim.execute({ claim_id: 'NOPE' }, TOOL_OPTS);
    expect(miss).toEqual({ error: "claim 'NOPE' not found" });
  });

  it('lookup_rule resolves by id, by code, and lists all', async () => {
    const one = (await tools.lookup_rule.execute({ rule_id: 'R001' }, TOOL_OPTS)) as {
      rule: { id: string };
    };
    expect(one.rule.id).toBe('R001');

    const byCode = (await tools.lookup_rule.execute({ code: '80048' }, TOOL_OPTS)) as {
      rules: { id: string }[];
    };
    expect(byCode.rules.some((r) => r.id === 'R001')).toBe(true);

    const all = (await tools.lookup_rule.execute({}, TOOL_OPTS)) as {
      rules: { id: string; type: string; description: string }[];
    };
    expect(all.rules).toHaveLength(RS.length);
    expect(all.rules[0]).toHaveProperty('description');
  });

  it('check_patient_history returns the patient other claims, excluding the current', async () => {
    const hist = (await tools.check_patient_history.execute(
      { patient_id: 'PT-1', exclude_claim_id: 'CLM-X' },
      TOOL_OPTS,
    )) as { prior_claims: { claim_id: string }[] };
    expect(hist.prior_claims.map((c) => c.claim_id)).toEqual(['CLM-Y']);
  });

  it('emit_finding records a valid finding', async () => {
    const r = await tools.emit_finding.execute(
      { rule_id: 'R001', defect_type: 'unbundling', line_refs: ['L1', 'L2'] },
      TOOL_OPTS,
    );
    expect(r).toMatchObject({ accepted: true });
    expect(ctx.emitted).toHaveLength(1);
    expect(ctx.emitted[0]?.claim_id).toBe('CLM-X'); // filled from currentClaimId
  });

  it('emit_finding PRESERVES the fabrication seam (records unsupported citations)', async () => {
    // A hallucinated rule id and a non-existent line still pass STRUCTURAL
    // validation and are recorded — catching them is the metric job, not the
    // tool's. (Matches claims_audit/tools.py emit_finding exactly.)
    const r = await tools.emit_finding.execute(
      { rule_id: 'R999', defect_type: 'unbundling', line_refs: ['L404'] },
      TOOL_OPTS,
    );
    expect(r).toMatchObject({ accepted: true });
    expect(ctx.emitted).toHaveLength(1);
    expect(ctx.emitted[0]?.rule_id).toBe('R999');
  });

  it('emit_finding rejects a structurally invalid finding', async () => {
    const badEnum = (await tools.emit_finding.execute(
      // @ts-expect-error deliberately invalid defect_type
      { rule_id: 'R001', defect_type: 'not_a_defect', line_refs: ['L1'] },
      TOOL_OPTS,
    )) as { accepted: boolean };
    expect(badEnum.accepted).toBe(false);

    const emptyRefs = (await tools.emit_finding.execute(
      { rule_id: 'R001', defect_type: 'unbundling', line_refs: [] },
      TOOL_OPTS,
    )) as { accepted: boolean };
    expect(emptyRefs.accepted).toBe(false);
    expect(ctx.emitted).toHaveLength(0);
  });
});
