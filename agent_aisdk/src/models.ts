/**
 * Zod data models — a field-for-field mirror of the Pydantic contract in
 * `claims_audit/models.py`. `Finding` in particular is the structured-output
 * type that `emit_finding` validates every agent-produced finding against, so a
 * finding that does not conform is rejected before it can reach the metrics.
 *
 * Parity notes (kept deliberately tight so the three arms are comparable):
 *   - `Severity` / `DefectType` enums match the Python `str, Enum` members.
 *   - `Finding` forbids extra fields (`.strict()` == Pydantic `extra="forbid"`),
 *     requires a non-empty `line_refs` (Pydantic `min_length=1`), defaults
 *     `severity` to "medium" and `rationale` to "".
 *   - The seam is preserved: `Finding` validates STRUCTURE only. It does NOT
 *     check that `rule_id` exists or that `line_refs` are real claim lines —
 *     catching those is the fabrication metric's job, exactly as in Python.
 */
import { z } from 'zod';

export const SeveritySchema = z.enum(['low', 'medium', 'high']);
export type Severity = z.infer<typeof SeveritySchema>;

export const DefectTypeSchema = z.enum([
  'unbundling',
  'upcoding',
  'duplicate',
  'units_exceeded',
  'missing_modifier',
]);
export type DefectType = z.infer<typeof DefectTypeSchema>;

// ---------------------------------------------------------------------------
// Claim structure (mirrors Patient / Provider / ClaimLine / Claim)
// ---------------------------------------------------------------------------

export const PatientSchema = z
  .object({
    patient_id: z.string(),
    year_of_birth: z.number().int().gte(1900).lte(2025),
    sex: z.enum(['F', 'M', 'U']),
  })
  .strict();
export type Patient = z.infer<typeof PatientSchema>;

export const ProviderSchema = z
  .object({
    npi: z.string(),
    name: z.string(),
    specialty: z.string(),
  })
  .strict();
export type Provider = z.infer<typeof ProviderSchema>;

export const ClaimLineSchema = z
  .object({
    line_id: z.string(),
    cpt: z.string(),
    units: z.number().int().gte(1),
    modifiers: z.array(z.string()).default([]),
    diagnosis_pointers: z.array(z.string()).default([]),
    charge: z.number().gte(0),
  })
  .strict();
export type ClaimLine = z.infer<typeof ClaimLineSchema>;

export const ClaimSchema = z
  .object({
    claim_id: z.string(),
    patient: PatientSchema,
    provider: ProviderSchema,
    date_of_service: z.string(),
    diagnoses: z.array(z.string()).default([]),
    lines: z.array(ClaimLineSchema),
    provider_notes: z.string().default(''),
  })
  .strict();
export type Claim = z.infer<typeof ClaimSchema>;

// ---------------------------------------------------------------------------
// Findings
// ---------------------------------------------------------------------------

/**
 * A single audit finding. Every finding MUST cite (a) a rule id and (b) at
 * least one claim-line span. Whether those actually exist is what the
 * fabrication-rate / citation-validity metrics check downstream.
 */
export const FindingSchema = z
  .object({
    claim_id: z.string(),
    rule_id: z.string(),
    defect_type: DefectTypeSchema,
    line_refs: z.array(z.string()).min(1),
    severity: SeveritySchema.default('medium'),
    rationale: z.string().default(''),
  })
  .strict();
export type Finding = z.infer<typeof FindingSchema>;

/**
 * The shape `emit_finding` accepts from the model. `claim_id` is optional here
 * because the agent audits one claim at a time; the tool fills it from the
 * active claim when omitted (mirroring the `agent_sdk` handler and the
 * `agent_graph` node, both of which stamp the claim id server-side).
 */
export const EmitFindingInputSchema = z
  .object({
    claim_id: z.string().optional(),
    rule_id: z.string(),
    defect_type: DefectTypeSchema,
    line_refs: z.array(z.string()).min(1),
    severity: SeveritySchema.optional(),
    rationale: z.string().optional(),
  })
  .strict();
export type EmitFindingInput = z.infer<typeof EmitFindingInputSchema>;

/** Canonical identity used for exact-match dedup (mirrors `Finding.key`). */
export function findingKey(f: Finding): string {
  return JSON.stringify([f.claim_id, f.rule_id, [...f.line_refs].sort()]);
}
