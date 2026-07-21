"""Deterministic rule engine.

Given a claim and the rule set, produce the exact set of findings the rules
imply. This is the project's spine:

* Both agents call these same per-rule checks through their tools, so the LLM's
  job is orchestration + reading free-text notes, never re-deriving edit logic.
* The engine is used directly as the deterministic ``engine`` eval arm, which is
  what the CI regression gate runs (no API key, fully reproducible).
* The synthetic-data generator is written to be *clean by construction* so that
  a claim with no injected defect yields zero engine findings; every injected
  defect is one the engine independently re-detects here. That is what makes the
  ground-truth labels well-defined.
"""

from __future__ import annotations

from collections import defaultdict

from claims_audit.models import Claim, ClaimLine, Finding, Severity
from claims_audit.rules import Rule, RuleSet, RuleType


def _has_override(line: ClaimLine, overrides: list[str]) -> bool:
    return any(m in overrides for m in line.modifiers)


class RuleEngine:
    """Evaluate all rules of the loaded rule set against a claim."""

    def __init__(self, ruleset: RuleSet):
        self.ruleset = ruleset

    # -- public API --------------------------------------------------------

    def evaluate(self, claim: Claim) -> list[Finding]:
        """Return findings for a single claim, sorted deterministically."""
        findings: list[Finding] = []
        for rule in self.ruleset:
            findings.extend(self._eval_rule(rule, claim))
        # Deterministic ordering: rule id, then sorted line refs.
        findings.sort(key=lambda f: (f.rule_id, sorted(f.line_refs)))
        return findings

    def evaluate_all(self, claims: list[Claim]) -> dict[str, list[Finding]]:
        return {c.claim_id: self.evaluate(c) for c in claims}

    # -- per-rule dispatch -------------------------------------------------

    def _eval_rule(self, rule: Rule, claim: Claim) -> list[Finding]:
        handler = {
            RuleType.NCCI_PAIR: self._eval_ncci_pair,
            RuleType.MUE_UNITS: self._eval_mue_units,
            RuleType.DUPLICATE: self._eval_duplicate,
            RuleType.MODIFIER_REQUIRED: self._eval_modifier_required,
            RuleType.UPCODING_EM: self._eval_upcoding_em,
        }[rule.type]
        return handler(rule, claim)

    def _finding(
        self, rule: Rule, claim: Claim, line_refs: list[str], rationale: str
    ) -> Finding:
        return Finding(
            claim_id=claim.claim_id,
            rule_id=rule.id,
            defect_type=rule.defect_type,
            line_refs=sorted(line_refs),
            severity=rule.severity,
            rationale=rationale,
        )

    # -- rule handlers -----------------------------------------------------

    def _eval_ncci_pair(self, rule: Rule, claim: Claim) -> list[Finding]:
        code_a = rule.params["code_a"]
        code_b = rule.params["code_b"]
        overrides = rule.params.get("override_modifiers", [])
        a_lines = [ln for ln in claim.lines if ln.cpt == code_a]
        b_lines = [ln for ln in claim.lines if ln.cpt == code_b]
        if not a_lines or not b_lines:
            return []
        # If ANY line in the pair carries an override modifier, the edit is
        # legitimately bypassed.
        if any(_has_override(ln, overrides) for ln in a_lines + b_lines):
            return []
        refs = [ln.line_id for ln in a_lines + b_lines]
        return [
            self._finding(
                rule,
                claim,
                refs,
                f"{code_a} and {code_b} billed together without modifier "
                f"{overrides[0] if overrides else ''}",
            )
        ]

    def _eval_mue_units(self, rule: Rule, claim: Claim) -> list[Finding]:
        code = rule.params["code"]
        max_units = int(rule.params["max_units_per_day"])
        code_lines = [ln for ln in claim.lines if ln.cpt == code]
        if not code_lines:
            return []
        total = sum(ln.units for ln in code_lines)
        if total <= max_units:
            return []
        refs = [ln.line_id for ln in code_lines]
        return [
            self._finding(
                rule,
                claim,
                refs,
                f"{code} billed {total} units/day; policy max is {max_units}",
            )
        ]

    def _eval_duplicate(self, rule: Rule, claim: Claim) -> list[Finding]:
        distinguishing = set(rule.params.get("distinguishing_modifiers", []))
        # Group lines by (cpt, modifiers minus distinguishing markers).
        groups: dict[tuple, list[ClaimLine]] = defaultdict(list)
        for ln in claim.lines:
            key = (ln.cpt, frozenset(m for m in ln.modifiers if m not in distinguishing))
            groups[key].append(ln)
        findings: list[Finding] = []
        for (cpt, _mods), lines in groups.items():
            if len(lines) < 2:
                continue
            # A distinguishing modifier on any duplicate makes the repeat legit.
            if any(set(ln.modifiers) & distinguishing for ln in lines):
                continue
            refs = [ln.line_id for ln in lines]
            findings.append(
                self._finding(
                    rule, claim, refs, f"{cpt} appears on {len(lines)} lines same DOS"
                )
            )
        return findings

    def _eval_modifier_required(self, rule: Rule, claim: Claim) -> list[Finding]:
        em_codes = set(rule.params["em_codes"])
        procedure_codes = set(rule.params["procedure_codes"])
        required = rule.params["required_modifier"]
        has_procedure = any(ln.cpt in procedure_codes for ln in claim.lines)
        if not has_procedure:
            return []
        findings: list[Finding] = []
        for ln in claim.lines:
            if ln.cpt in em_codes and required not in ln.modifiers:
                findings.append(
                    self._finding(
                        rule,
                        claim,
                        [ln.line_id],
                        f"E/M {ln.cpt} billed with a procedure but missing modifier {required}",
                    )
                )
        return findings

    def _eval_upcoding_em(self, rule: Rule, claim: Claim) -> list[Finding]:
        code = rule.params["code"]
        keywords = [k.lower() for k in rule.params["required_keywords"]]
        note = (claim.provider_notes or "").lower()
        supported = any(k in note for k in keywords)
        if supported:
            return []
        findings: list[Finding] = []
        for ln in claim.lines:
            if ln.cpt == code:
                findings.append(
                    self._finding(
                        rule,
                        claim,
                        [ln.line_id],
                        f"{code} billed but note lacks supporting documentation",
                    )
                )
        return findings


def severity_rank(sev: Severity) -> int:
    return {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}[sev]
