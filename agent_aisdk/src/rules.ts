/**
 * Rule-set loading — mirrors `claims_audit/rules.py`. The YAML in
 * `rules/audit_rules.yaml` is the single source of truth; the deterministic
 * engine, both Python agents, and this arm all read the same file. We parse it
 * (never re-encode it) so there is no chance of rule drift between substrates.
 */
import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { z } from 'zod';
import { DefectTypeSchema, SeveritySchema } from './models.js';
import { RULES_PATH } from './paths.js';

export const RuleTypeSchema = z.enum([
  'ncci_pair',
  'mue_units',
  'duplicate',
  'modifier_required',
  'upcoding_em',
]);
export type RuleType = z.infer<typeof RuleTypeSchema>;

export const RuleSchema = z
  .object({
    id: z.string(),
    type: RuleTypeSchema,
    defect_type: DefectTypeSchema,
    severity: SeveritySchema.default('medium'),
    description: z.string(),
    params: z.record(z.string(), z.unknown()).default({}),
  })
  .strict();
export type Rule = z.infer<typeof RuleSchema>;

const RuleFileSchema = z.object({ rules: z.array(RuleSchema) });

export class RuleSet {
  readonly rules: readonly Rule[];
  private readonly byIdMap: Map<string, Rule>;

  constructor(rules: readonly Rule[]) {
    const ids = rules.map((r) => r.id);
    const unique = new Set(ids);
    if (unique.size !== ids.length) {
      const dupes = [...unique].filter((id) => ids.filter((x) => x === id).length > 1).sort();
      throw new Error(`Duplicate rule ids: ${dupes.join(', ')}`);
    }
    this.rules = rules;
    this.byIdMap = new Map(rules.map((r) => [r.id, r]));
  }

  byId(ruleId: string | undefined | null): Rule | undefined {
    if (ruleId == null) return undefined;
    return this.byIdMap.get(ruleId);
  }

  ids(): Set<string> {
    return new Set(this.byIdMap.keys());
  }

  [Symbol.iterator](): Iterator<Rule> {
    return this.rules[Symbol.iterator]();
  }

  get length(): number {
    return this.rules.length;
  }
}

export function loadRules(path: string = RULES_PATH): RuleSet {
  const raw: unknown = parse(readFileSync(path, 'utf-8'));
  const parsed = RuleFileSchema.parse(raw);
  return new RuleSet(parsed.rules);
}
