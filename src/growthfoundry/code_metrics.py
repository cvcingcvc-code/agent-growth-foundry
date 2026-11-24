"""Coding-task metrics: syntax pass rate, unit-test pass rate, patch success
rate, repetition-loop rate and task relevance.

Pure functions over recorded task results, so the whole metric layer is
testable without any GPU or model. These metrics are quality signals for the
growth loop, not a final release approval.

Repetition detection (round-4.1 unified rule): the 2-gram word-frequency
check was removed because it false-positives on code and topical words
(e.g. "评测集" appearing several times in an answer about 评测集). The real
failure modes (sft-020) are caught by exactly two signals, implemented HERE
and re-used everywhere (candidate_audit, regression, coding pipeline):
- sentence-level loop: the same non-trivial sentence appears >=2 times
  (split on 。！？!?；; and newlines);
- consecutive duplicate code lines: >=3 identical non-empty lines in a row.
Variable-name reuse and topical-word reuse are NOT flagged.
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass, field

# Kept for backward compatibility of imports only; the word-frequency
# threshold semantics are deprecated by the unified repetition rule.
REPEAT_THRESHOLD = 3
MIN_LEN_CHARS = 12
OVERLAP_FLOOR = 0.15
CONSECUTIVE_DUP_LINES = 3
SENTENCE_LOOP_THRESHOLD = 2

_SENTENCE_SPLIT_RE = re.compile(r'[。！？!?；;\n]')

_STOPWORDS = {"的", "了", "是", "在", "和", "与", "或", "一个", "如果", "可以", "需要",
              "the", "a", "an", "of", "to", "is", "are", "and", "or", "if", "for", "in"}


# ---------- syntax ----------

def extract_code_blocks(text: str) -> list[str]:
    """Fenced ```python blocks first; fall back to the raw text as one block."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", str(text or ""), flags=re.DOTALL)
    if blocks:
        return [b for b in blocks if b.strip()]
    text = str(text or "").strip()
    return [text] if text else []


def is_valid_python(code: str) -> tuple[bool, str]:
    """ast.parse check; returns (ok, error)."""
    try:
        ast.parse(str(code or ""))
        return True, ''
    except SyntaxError as ex:
        return False, f'line {ex.lineno}: {ex.msg}'


def syntax_pass_rate(answers: list[str]) -> dict:
    """Rate of answers whose extracted code parses; 0.0 for empty input."""
    results, errors = [], []
    for a in answers:
        blocks = extract_code_blocks(a)
        if not blocks:
            results.append(False)
            errors.append({'answer_index': len(results) - 1, 'error': 'no code found'})
            continue
        ok = all(is_valid_python(b)[0] for b in blocks)
        results.append(ok)
        if not ok:
            for b in blocks:
                ok_b, err = is_valid_python(b)
                if not ok_b:
                    errors.append({'answer_index': len(results) - 1, 'error': err})
                    break
    n = len(answers)
    return {'total': n, 'passed': sum(results), 'rate': round(sum(results) / n, 4) if n else 0.0,
            'errors': errors}


# ---------- repetition (round-4.1 unified rule; authoritative) ----------

def _words(text: str) -> list[str]:
    """CJK bigrams + latin words, stopword-filtered. Used by the relevance
    overlap metrics only - NOT by repetition detection any more."""
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
    return [g for g in grams if g not in _STOPWORDS]


def has_sentence_loop(text: str, threshold: int = SENTENCE_LOOP_THRESHOLD,
                      min_len_chars: int = 5) -> bool:
    """True when the same non-trivial sentence appears >=threshold times.

    Prose form of the sft-020 failure mode: pathological whole-sentence
    loops (min length 5 catches short phrase loops like sft-020's
    "需手动重置" x3). Topical-word reuse is NOT flagged (see module docstring).
    """
    text = str(text or '').strip()
    if len(text) < min_len_chars:
        return False
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text)
                 if len(s.strip()) >= min_len_chars]
    counts: dict[str, int] = {}
    for s in sentences:
        counts[s] = counts.get(s, 0) + 1
    return max(counts.values(), default=0) >= threshold


def has_consecutive_dup_lines(code: str, threshold: int = CONSECUTIVE_DUP_LINES) -> bool:
    """Code form of the sft-020 failure mode: >=threshold identical
    non-empty lines appear back-to-back."""
    run, prev = 1, None
    for line in str(code or '').splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == prev:
            run += 1
            if run >= threshold:
                return True
        else:
            run, prev = 1, stripped
    return False


def has_repetition_loop(answer: str, threshold: int = SENTENCE_LOOP_THRESHOLD) -> bool:
    """Unified repetition signal (round-4.1).

    Dispatches on answer shape: sentence-level loop for the prose part,
    consecutive-duplicate-lines for the code part. Replaces the removed
    2-gram word-frequency check that false-positived on code and topics.
    """
    text = str(answer or '').strip()
    if len(text) < MIN_LEN_CHARS:
        return False
    blocks = extract_code_blocks(text)
    if blocks:
        # Code answer: only the code-form signal applies. Split off the
        # fenced blocks and check the remaining prose separately.
        prose = re.sub(r"```(?:python|py)?\s*\n.*?```", '', text, flags=re.DOTALL)
        return (has_consecutive_dup_lines('\n'.join(blocks))
                or has_sentence_loop(prose.strip()))
    return has_sentence_loop(text)


def repetition_loop_rate(answers: list[str]) -> dict:
    n = len(answers)
    flagged = [i for i, a in enumerate(answers) if has_repetition_loop(a)]
    return {'total': n, 'flagged': len(flagged), 'rate': round(len(flagged) / n, 4) if n else 0.0,
            'flagged_indexes': flagged}


# ---------- task relevance (same failure mode as sft-019) ----------

def reference_overlap(answer: str, reference: str) -> float:
    a, r = set(_words(answer)), set(_words(reference))
    if not a or not r:
        return 0.0
    return len(a & r) / min(len(a), len(r))


def task_relevance_rate(answers: list[str], references: list[str]) -> dict:
    """Share of answers that stay on-topic vs the reference question intent."""
    assert len(answers) == len(references), 'answers/references length mismatch'
    n = len(answers)
    on_topic, details = 0, []
    for i, (a, r) in enumerate(zip(answers, references)):
        ov = reference_overlap(a, r)
        ok = ov >= OVERLAP_FLOOR
        on_topic += ok
        details.append({'index': i, 'overlap': round(ov, 4), 'on_topic': ok})
    return {'total': n, 'on_topic': on_topic, 'rate': round(on_topic / n, 4) if n else 0.0,
            'items': details}


# ---------- execution-based ----------

def unit_test_pass_rate(results: list[bool]) -> dict:
    """results[i] = whether the generated code passed the task's test suite."""
    n = len(results)
    passed = sum(1 for r in results if r)
    return {'total': n, 'passed': passed, 'rate': round(passed / n, 4) if n else 0.0}


def patch_success_rate(attempts: list[dict]) -> dict:
    """attempts: [{'task': str, 'buggy_passed': bool, 'patched_passed': bool}].
    Patch success = buggy originally failing AND patched now passing."""
    eligible = [a for a in attempts if not a.get('buggy_passed', True)]
    fixed = [a for a in eligible if a.get('patched_passed')]
    return {'total': len(eligible), 'patched': len(fixed),
            'rate': round(len(fixed) / len(eligible), 4) if eligible else 0.0}


# ---------- combined report ----------

def summarize(answers: list[str], references: list[str] | None = None,
              test_results: list[bool] | None = None,
              patch_attempts: list[dict] | None = None) -> dict:
    ref = references if references is not None else [''] * len(answers)
    summary = {
        'syntax': syntax_pass_rate(answers),
        'repetition': repetition_loop_rate(answers),
        'relevance': task_relevance_rate(answers, ref),
        'unit_test': unit_test_pass_rate(test_results) if test_results is not None else None,
        'patch': patch_success_rate(patch_attempts) if patch_attempts is not None else None,
    }
    return summary
