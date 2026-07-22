import { describe, expect, it } from 'vitest';
import {
  DefectTypeSchema,
  EmitFindingInputSchema,
  FindingSchema,
  SeveritySchema,
} from '../src/models.js';

describe('Finding schema mirrors the Pydantic contract', () => {
  it('enums match the Python DefectType / Severity members', () => {
    expect(DefectTypeSchema.options).toEqual([
      'unbundling',
      'upcoding',
      'duplicate',
      'units_exceeded',
      'missing_modifier',
    ]);
    expect(SeveritySchema.options).toEqual(['low', 'medium', 'high']);
  });

  it('forbids extra fields (extra="forbid")', () => {
    const r = FindingSchema.safeParse({
      claim_id: 'C1',
      rule_id: 'R001',
      defect_type: 'unbundling',
      line_refs: ['L1'],
      smuggled: true,
    });
    expect(r.success).toBe(false);
  });

  it('requires a non-empty line_refs (min_length=1)', () => {
    const r = FindingSchema.safeParse({
      claim_id: 'C1',
      rule_id: 'R001',
      defect_type: 'unbundling',
      line_refs: [],
    });
    expect(r.success).toBe(false);
  });

  it('defaults severity to medium and rationale to ""', () => {
    const r = FindingSchema.parse({
      claim_id: 'C1',
      rule_id: 'R001',
      defect_type: 'unbundling',
      line_refs: ['L1'],
    });
    expect(r.severity).toBe('medium');
    expect(r.rationale).toBe('');
  });

  it('does NOT validate rule/line existence (the fabrication seam)', () => {
    // A structurally valid finding citing a non-existent rule/line still parses:
    // catching that is the metric's job, not the schema's.
    const r = FindingSchema.safeParse({
      claim_id: 'C1',
      rule_id: 'R999',
      defect_type: 'unbundling',
      line_refs: ['L404'],
    });
    expect(r.success).toBe(true);
  });

  it('emit input allows optional claim_id/severity/rationale', () => {
    const r = EmitFindingInputSchema.parse({
      rule_id: 'R001',
      defect_type: 'duplicate',
      line_refs: ['L1', 'L2'],
    });
    expect(r.claim_id).toBeUndefined();
    expect(r.rule_id).toBe('R001');
  });
});
