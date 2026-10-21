"""Coding-task metrics: syntax pass rate, unit-test pass rate, patch success
rate, repetition-loop rate and task relevance.

Pure functions over recorded task results, so the whole metric layer is
testable without any GPU or model. These metrics are quality signals for the
growth loop, not a final release approval.
"""
from __future__ import annotations
import ast
import re
from dataclasses import dataclass, field

REPEAT_THRESHOLD = 3
MIN_LEN_CHARS = 12
OVERLAP_FLOOR = 0.15

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


# ---------- repetition (same failure mode as sft-020) ----------

def _words(text: str) -> list[str]:
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


def has_repetition_loop(answer: str, threshold: int = REPEAT_THRESHOLD) -> bool:
    text = str(answer or "").strip()
    if len(text) < MIN_LEN_CHARS:
        return False
    words = _words(text)
    if not words:
        return False
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return max(counts.values()) >= threshold


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
