/**
 * Shared prompt + serialization — a faithful port of `claims_audit/prompting.py`.
 * The three arms send the model the same task framing and the same rendered view
 * of a claim and the rule set, so any accuracy difference is attributable to
 * orchestration, not prompt drift. The SYSTEM_PROMPT text is byte-for-byte the
 * resolved Python string; `renderRules` / `renderClaim` reproduce the same
 * compact rule lines and the same claim field ordering.
 */
import type { Claim } from './models.js';
import type { RuleSet } from './rules.js';

export const SYSTEM_PROMPT = `You are a medical-claims line-item auditor. You examine one claim at a time and report billing defects, citing the exact rule and claim lines involved.

You audit against a fixed, machine-readable rule set. You may ONLY report a defect that corresponds to one of those rules. For every finding you MUST:
  * cite the rule_id of the violated rule (it must be a real rule id), and
  * cite the line_refs (the claim's line ids, e.g. "L1") the defect involves.

Never invent a rule id or a line id. If no rule is violated, report nothing. Prefer precision: only report a defect when the rule's conditions are clearly met. For E/M up-coding rules, read the free-text provider note and decide whether it documents the level of service billed.

Defect categories: unbundling, upcoding, duplicate, units_exceeded, missing_modifier. Use the defect_type from the cited rule.
`;

/** Compact, model-friendly rendering of every rule (mirrors `render_rules`). */
export function renderRules(ruleset: RuleSet): string {
  const lines: string[] = [];
  for (const r of ruleset) {
    const params = JSON.stringify(r.params);
    const desc = r.description.split(/\s+/).filter(Boolean).join(' ');
    lines.push(
      `- ${r.id} [${r.type}] defect=${r.defect_type} severity=${r.severity}: ${desc} params=${params}`,
    );
  }
  return lines.join('\n');
}

/**
 * Render a claim as compact JSON in the same field order the Python
 * `Claim.model_dump(mode="json")` produces, so the two views match.
 */
export function renderClaim(claim: Claim): string {
  const ordered = {
    claim_id: claim.claim_id,
    patient: {
      patient_id: claim.patient.patient_id,
      year_of_birth: claim.patient.year_of_birth,
      sex: claim.patient.sex,
    },
    provider: {
      npi: claim.provider.npi,
      name: claim.provider.name,
      specialty: claim.provider.specialty,
    },
    date_of_service: claim.date_of_service,
    diagnoses: claim.diagnoses,
    lines: claim.lines.map((ln) => ({
      line_id: ln.line_id,
      cpt: ln.cpt,
      units: ln.units,
      modifiers: ln.modifiers,
      diagnosis_pointers: ln.diagnosis_pointers,
      charge: ln.charge,
    })),
    provider_notes: claim.provider_notes,
  };
  return JSON.stringify(ordered, null, 2);
}

/** The per-claim instruction used by all arms (mirrors `audit_task_prompt`). */
export function auditTaskPrompt(claim: Claim, ruleset: RuleSet): string {
  return (
    `Audit this claim and emit one finding per distinct defect.\n\n` +
    `RULES:\n${renderRules(ruleset)}\n\n` +
    `CLAIM:\n${renderClaim(claim)}\n\n` +
    `For each defect, cite the rule_id and the involved line_refs. ` +
    `If the claim is clean, emit no findings.`
  );
}
