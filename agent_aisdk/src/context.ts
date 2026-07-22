/**
 * `AuditContext` — the per-session state the four tools read from / write to.
 * Mirrors `ToolContext` in `claims_audit/tools.py`: a claims map, the rule set,
 * a patient -> claim-ids history index, the id of the claim currently being
 * audited, and the findings emitted so far.
 */
import type { Claim, Finding } from './models.js';
import type { RuleSet } from './rules.js';

export class AuditContext {
  readonly claims: Map<string, Claim>;
  readonly ruleset: RuleSet;
  readonly history: Map<string, string[]>;
  currentClaimId: string | null = null;
  emitted: Finding[] = [];

  private constructor(claims: Map<string, Claim>, ruleset: RuleSet, history: Map<string, string[]>) {
    this.claims = claims;
    this.ruleset = ruleset;
    this.history = history;
  }

  static build(claims: Claim[], ruleset: RuleSet): AuditContext {
    const claimMap = new Map<string, Claim>();
    const history = new Map<string, string[]>();
    for (const c of claims) {
      claimMap.set(c.claim_id, c);
      const prior = history.get(c.patient.patient_id) ?? [];
      prior.push(c.claim_id);
      history.set(c.patient.patient_id, prior);
    }
    return new AuditContext(claimMap, ruleset, history);
  }

  resetEmitted(): void {
    this.emitted = [];
  }
}
