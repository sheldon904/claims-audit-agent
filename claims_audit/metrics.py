"""Eval metrics: precision/recall, fabrication rate, citation validity.

A *predicted* finding is scored against the *ground-truth* findings for the same
claim. Matching is intentionally lenient on the exact line span but strict on
identity: a predicted finding matches a ground-truth finding when they share the
same ``(claim_id, rule_id)`` and their ``line_refs`` overlap. Matching is greedy
1-to-1 so two predictions can't both claim credit for one ground-truth defect.

Definitions
-----------
precision            TP / (TP + FP)      of what the agent flagged, how much was real
recall               TP / (TP + FN)      of the real defects, how many were caught
citation_validity    valid_citations / predicted
                     a citation is valid iff rule_id exists in the rule set AND
                     every line_ref exists on the cited claim
fabrication_rate     1 - citation_validity
                     the fraction of findings that point at a rule or a line that
                     does not exist (the metric that must be ~0 for trust)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from claims_audit.models import Claim, Finding
from claims_audit.rules import RuleSet


@dataclass
class EvalResult:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    predicted_count: int = 0
    ground_truth_count: int = 0
    invalid_citations: int = 0
    # (claim_id, rule_id, sorted line_refs) tuples, for debugging / reports.
    unmatched_predictions: list[tuple] = field(default_factory=list)
    missed_ground_truth: list[tuple] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def citation_validity(self) -> float:
        if self.predicted_count == 0:
            return 1.0
        return (self.predicted_count - self.invalid_citations) / self.predicted_count

    @property
    def fabrication_rate(self) -> float:
        return 1.0 - self.citation_validity

    def as_dict(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "citation_validity": round(self.citation_validity, 4),
            "fabrication_rate": round(self.fabrication_rate, 4),
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "predicted_count": self.predicted_count,
            "ground_truth_count": self.ground_truth_count,
            "invalid_citations": self.invalid_citations,
        }


def _citation_is_valid(finding: Finding, claim: Claim | None, ruleset: RuleSet) -> bool:
    if ruleset.by_id(finding.rule_id) is None:
        return False
    if claim is None:
        return False
    claim_lines = claim.line_ids()
    return all(ref in claim_lines for ref in finding.line_refs)


def _matches(pred: Finding, gt: Finding) -> bool:
    return (
        pred.claim_id == gt.claim_id
        and pred.rule_id == gt.rule_id
        and bool(set(pred.line_refs) & set(gt.line_refs))
    )


def score_claim(
    predicted: list[Finding],
    ground_truth: list[Finding],
    claim: Claim | None,
    ruleset: RuleSet,
) -> EvalResult:
    """Score one claim's predictions against its ground truth."""
    result = EvalResult(
        predicted_count=len(predicted),
        ground_truth_count=len(ground_truth),
    )

    # Citation validity is independent of matching.
    for p in predicted:
        if not _citation_is_valid(p, claim, ruleset):
            result.invalid_citations += 1

    # Greedy 1-to-1 matching of predictions to ground truth.
    remaining_gt = list(ground_truth)
    for p in predicted:
        hit_idx = next((i for i, g in enumerate(remaining_gt) if _matches(p, g)), None)
        if hit_idx is not None:
            result.true_positives += 1
            remaining_gt.pop(hit_idx)
        else:
            result.false_positives += 1
            result.unmatched_predictions.append(
                (p.claim_id, p.rule_id, tuple(sorted(p.line_refs)))
            )
    for g in remaining_gt:
        result.false_negatives += 1
        result.missed_ground_truth.append(
            (g.claim_id, g.rule_id, tuple(sorted(g.line_refs)))
        )
    return result


def aggregate(results: list[EvalResult]) -> EvalResult:
    """Micro-average a list of per-claim results into one."""
    total = EvalResult()
    for r in results:
        total.true_positives += r.true_positives
        total.false_positives += r.false_positives
        total.false_negatives += r.false_negatives
        total.predicted_count += r.predicted_count
        total.ground_truth_count += r.ground_truth_count
        total.invalid_citations += r.invalid_citations
        total.unmatched_predictions.extend(r.unmatched_predictions)
        total.missed_ground_truth.extend(r.missed_ground_truth)
    return total


def score_dataset(
    predictions: dict[str, list[Finding]],
    ground_truth: dict[str, list[Finding]],
    claims: dict[str, Claim],
    ruleset: RuleSet,
) -> EvalResult:
    """Score predictions for a whole dataset keyed by claim_id."""
    per_claim = []
    all_ids = set(predictions) | set(ground_truth)
    for cid in sorted(all_ids):
        per_claim.append(
            score_claim(
                predictions.get(cid, []),
                ground_truth.get(cid, []),
                claims.get(cid),
                ruleset,
            )
        )
    return aggregate(per_claim)
