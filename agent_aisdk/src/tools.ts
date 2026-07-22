/**
 * The four audit tools, reimplemented on the Vercel AI SDK with `tool()` +
 * Zod, as genuine ports of the shared core in `claims_audit/tools.py` (NOT a
 * parallel contract). `fetch_claim`, `lookup_rule`, `check_patient_history`
 * gather evidence; `emit_finding` records one validated finding.
 *
 * As in Python, `emit_finding` performs STRUCTURAL validation only (the Zod
 * `Finding` contract). It deliberately does NOT reject a structurally-valid
 * finding that cites a non-existent rule or line — catching those is the job of
 * the fabrication-rate metric, and silently dropping them would make that
 * metric meaningless. That seam is what keeps this arm comparable to the
 * `claude-agent-sdk` arm (both let the model drive; neither prunes citations).
 */
import { tool } from 'ai';
import { z } from 'zod';
import type { AuditContext } from './context.js';
import { EmitFindingInputSchema, type Finding, FindingSchema } from './models.js';

function asStr(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  return ''; // codes are scalar; objects/arrays are never a CPT match target
}

export function buildTools(ctx: AuditContext) {
  return {
    fetch_claim: tool({
      description: 'Fetch the full claim record (patient stub, lines, notes) by id.',
      inputSchema: z.object({ claim_id: z.string() }),
      execute: ({ claim_id }) => {
        const claim = ctx.claims.get(claim_id);
        if (claim === undefined) return { error: `claim '${claim_id}' not found` };
        return claim;
      },
    }),

    lookup_rule: tool({
      description:
        'Look up audit rules. Provide rule_id for one rule, code for all rules ' +
        'referencing a CPT code, or neither to list every rule.',
      inputSchema: z.object({
        rule_id: z.string().optional(),
        code: z.string().optional(),
      }),
      execute: ({ rule_id, code }) => {
        if (rule_id !== undefined) {
          const rule = ctx.ruleset.byId(rule_id);
          if (rule === undefined) return { error: `rule '${rule_id}' not found` };
          return { rule };
        }
        if (code !== undefined) {
          const matches = [];
          for (const r of ctx.ruleset) {
            const p = r.params;
            const referenced = new Set<string>([
              asStr(p['code']),
              asStr(p['code_a']),
              asStr(p['code_b']),
              ...(Array.isArray(p['em_codes']) ? p['em_codes'].map(asStr) : []),
              ...(Array.isArray(p['procedure_codes']) ? p['procedure_codes'].map(asStr) : []),
            ]);
            if (referenced.has(code)) matches.push(r);
          }
          return { rules: matches };
        }
        return {
          rules: ctx.ruleset.rules.map((r) => ({
            id: r.id,
            type: r.type,
            description: r.description.trim(),
          })),
        };
      },
    }),

    check_patient_history: tool({
      description:
        "Return the patient's other claims to check for cross-claim duplicates/frequency.",
      inputSchema: z.object({
        patient_id: z.string(),
        exclude_claim_id: z.string().optional(),
      }),
      execute: ({ patient_id, exclude_claim_id }) => {
        const claimIds = ctx.history.get(patient_id) ?? [];
        const prior = [];
        for (const cid of claimIds) {
          if (cid === exclude_claim_id) continue;
          const c = ctx.claims.get(cid);
          if (c === undefined) continue;
          prior.push({
            claim_id: c.claim_id,
            date_of_service: c.date_of_service,
            lines: c.lines.map((ln) => ({
              cpt: ln.cpt,
              units: ln.units,
              modifiers: ln.modifiers,
            })),
          });
        }
        return { patient_id, prior_claims: prior };
      },
    }),

    emit_finding: tool({
      description:
        'Emit one audit finding. Must cite an existing rule_id and at least one ' +
        'existing claim line_ref. Validated against the Finding schema.',
      inputSchema: EmitFindingInputSchema,
      execute: (input) => {
        const candidate = {
          claim_id: input.claim_id ?? ctx.currentClaimId ?? '',
          rule_id: input.rule_id,
          defect_type: input.defect_type,
          line_refs: input.line_refs,
          severity: input.severity ?? 'medium',
          rationale: input.rationale ?? '',
        };
        const parsed = FindingSchema.safeParse(candidate);
        if (!parsed.success) {
          return {
            accepted: false,
            errors: parsed.error.issues.map((e) => ({
              loc: e.path,
              msg: e.message,
            })),
          };
        }
        const finding: Finding = parsed.data;
        ctx.emitted.push(finding);
        return { accepted: true, finding_key: [finding.claim_id, finding.rule_id] };
      },
    }),
  };
}

export type AuditTools = ReturnType<typeof buildTools>;
