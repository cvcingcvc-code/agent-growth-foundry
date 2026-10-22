"""Regression gate: automatic PROMOTE/HOLD decision between model versions.

Logic (transparent, deterministic, testable):
1. Degeneration signals per eval sample:
   - repetition loop: round-4.1 unified rule (sentence-level loop in prose
     or >=3 consecutive identical code lines; the old 2-gram word-frequency
     check was removed because it false-positived on code and topical words)
   - low reference overlap: answer shares too few meaningful words with the
     human-written reference answer (round-2 sft-019 off-topic signal)
2. Promotion decision (AGENTS.md rule 7):
   - candidate eval_loss must improve on the previous version
   - degenerated samples must not increase
   - hard cap on tolerated regressions (default: 0)
   - only then PROMOTE; otherwise HOLD (keep the previous version)
This is a quality gate, not a legal or final release approval.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from growthfoundry.code_metrics import has_repetition_loop

# Kept for backward compatibility of imports only; semantics now delegated
# to the unified repetition rule in code_metrics.
REPEAT_THRESHOLD = 3
MIN_ANSWER_CHARS = 12
# Meaningful-word overlap with reference below this ratio signals off-topic.
OVERLAP_FLOOR = 0.15


@dataclass(frozen=True)
class SampleCheck:
    source_id: str
    repetition_loop: bool
    low_reference_overlap: float | None  # None when no reference available
    degenerated: bool
    reason: str


@dataclass(frozen=True)
class PromotionDecision:
    decision: str  # PROMOTE / HOLD
    reasons: list[str] = field(default_factory=list)
    new_degenerated: int = 0
    old_degenerated: int = 0


def _words(text: str) -> list[str]:
    # crude CJK+latin word split: CJK bigrams + latin words; stopword-filtered
    # (used by reference overlap only; repetition uses the unified rule)
    text = str(text or "").strip()
    if not text:
        return []
    latin = re.findall(r"[A-Za-z0-9]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]+", text)
    grams: list[str] = list(w.lower() for w in latin)
    for run in cjk:
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return [g for g in grams if g not in _OVERLAP_STOPWORDS]


# Stopwords for the reference-overlap metric only.
_OVERLAP_STOPWORDS = {"的", "了", "是", "在", "和", "与", "或", "一个", "如果", "可以", "需要",
                      "the", "a", "an", "of", "to", "is", "are", "and", "or", "if", "for", "in"}


def check_repetition(answer: str, threshold: int = REPEAT_THRESHOLD) -> bool:
    """Unified repetition signal (round-4.1): delegates to code_metrics.

    The old 2-gram word-frequency check is replaced by the sentence-level
    loop + consecutive-duplicate-lines rule, so the regression gate, the
    candidate audit and the coding pipeline all share one judgment.
    """
    return has_repetition_loop(answer)


def reference_overlap(answer: str, reference: str) -> float:
    """Jaccard-style overlap of meaningful words between answer and reference."""
    a, r = set(_words(answer)), set(_words(reference))
    if not a or not r:
        return 0.0
    return len(a & r) / min(len(a), len(r))


def check_sample(source_id: str, answer: str, reference: str) -> SampleCheck:
    rep = check_repetition(answer)
    ov: float | None = None
    if reference and reference.strip():
        ov = reference_overlap(answer, reference)
    degenerated = rep or (ov is not None and ov < OVERLAP_FLOOR)
    reasons = []
    if rep:
        reasons.append("repetition-loop")
    if ov is not None and ov < OVERLAP_FLOOR:
        reasons.append(f"low-reference-overlap({ov:.2f})")
    return SampleCheck(source_id, rep, ov, degenerated, ";".join(reasons) or "ok")


def decide_promotion(new_metrics: dict, old_metrics: dict,
                     new_checks: list[SampleCheck], old_checks: list[SampleCheck],
                     *, max_regressions: int = 0) -> PromotionDecision:
    """Deterministic PROMOTE/HOLD per AGENTS.md rule 7.

    new_metrics/old_metrics must contain 'eval_loss'.
    Promotion requires: eval_loss improved AND degenerated-sample count not
    increased AND regression count <= max_regressions.
    """
    new_loss = float(new_metrics.get("eval_loss") or 0) if new_metrics.get("eval_loss") is not None else None
    old_loss = float(old_metrics.get("eval_loss") or 0) if old_metrics.get("eval_loss") is not None else None
    reasons: list[str] = []
    if new_loss is None or old_loss is None:
        return PromotionDecision("HOLD", ["missing eval_loss; cannot compare versions"],
                                 sum(1 for c in new_checks if c.degenerated),
                                 sum(1 for c in old_checks if c.degenerated))
    loss_ok = new_loss < old_loss
    reasons.append(f"eval_loss {old_loss:.3f} -> {new_loss:.3f} ({'improved' if loss_ok else 'NOT improved'})")
    new_deg = sum(1 for c in new_checks if c.degenerated)
    old_deg = sum(1 for c in old_checks if c.degenerated)
    deg_ok = new_deg <= old_deg
    reasons.append(f"degenerated samples {old_deg} -> {new_deg} ({'ok' if deg_ok else 'increased'})")
    old_by_id = {c.source_id: c for c in old_checks}
    regressions = [c.source_id for c in new_checks
                   if not old_by_id.get(c.source_id, c).degenerated and c.degenerated]
    if regressions:
        reasons.append("new regressions: " + ",".join(regressions))
    if loss_ok and deg_ok and len(regressions) <= max_regressions:
        return PromotionDecision("PROMOTE", reasons, new_deg, old_deg)
    return PromotionDecision("HOLD", reasons, new_deg, old_deg)


def summarize_checks(checks: list[SampleCheck]) -> dict:
    return {
        "samples": len(checks),
        "degenerated": sum(1 for c in checks if c.degenerated),
        "items": [{"source_id": c.source_id, "repetition_loop": c.repetition_loop,
                   "reference_overlap": c.low_reference_overlap,
                   "degenerated": c.degenerated, "reason": c.reason} for c in checks],
    }
