"""Rule-based audit for candidate training samples before they may enter training.

A candidate is only written to the approved pool when every per-type rule
passes. The audit is deliberately conservative: anything it cannot verify is
rejected with an explicit reason (matches AGENTS.md rule 6/7).

Per-type checks (on top of the shared schema/dedup/repetition checks):
- code_gen: fenced Python code parses, defines the target function,
  no >=3 consecutive identical code lines.
- debug: fenced Python code parses and mentions the target function,
  no >=3 consecutive identical code lines.
- qa: every declared key term appears in the answer.
- counterexample_019 (anti off-topic, sft-019): the answer itself must be
  valid Python (a direct minimal answer), length <= 80 chars.
- counterexample_020 (anti repetition loop, sft-020): at most one sentence,
  length 10..80 chars.

Shared checks for every record: schema fields, unique source_id, unique
(question, answer) pair, prose part free of repetition loops, non-trivial
answer length. Repetition is checked on the PROSE part only, because normal
code legitimately reuses variable names; the code equivalent of a repetition
loop is >=3 consecutive identical lines.
"""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path

from growthfoundry.code_metrics import (
    extract_code_blocks, has_consecutive_dup_lines, has_sentence_loop,
    has_repetition_loop, is_valid_python,
)

TASK_TYPES = {"code_gen", "debug", "qa", "counterexample_019", "counterexample_020"}
# Repetition detection delegates to code_metrics (round-4.1 unified rule):
# has_sentence_loop (prose) + has_consecutive_dup_lines (code) live there and
# are shared with the regression gate and the coding pipeline.
CONSECUTIVE_DUP_LINES = 3
MAX_019_LEN = 80
MIN_020_LEN = 10
MAX_020_LEN = 80
SENTENCE_ENDINGS = ('。', '！', '？')

# ---------- splitting ----------

def split_prose_and_code(answer: str) -> tuple[str, list[str]]:
    """Return (prose_without_fences, code_blocks)."""
    text = str(answer or '')
    blocks = extract_code_blocks(text)
    prose = re.sub(r"```(?:python|py)?\s*\n.*?```", '', text, flags=re.DOTALL)
    return prose.strip(), blocks


# ---------- code-level checks ----------

def defines_function(code: str, func_name: str) -> bool:
    return bool(re.search(rf"def\s+{re.escape(func_name)}\s*\(", str(code or '')))


# has_sentence_loop / has_consecutive_dup_lines are imported from
# code_metrics.py (round-4.1 unified repetition rule, single source of truth).


# ---------- per-type rule checks ----------

def check_record(item: dict) -> list[str]:
    """Return a list of failure reasons; empty list means the record passes."""
    reasons: list[str] = []
    ttype = item.get('task_type')
    answer = item.get('messages', [{}, {}])[-1].get('content', '')
    prose, blocks = split_prose_and_code(answer)

    if ttype not in TASK_TYPES:
        return [f'unknown task_type: {ttype}']
    if len(answer.strip()) < 6:
        return ['answer too short (<6 chars)']
    # Sentence-level repetition is the prose equivalent of the sft-020
    # failure mode. Topical-word reuse is normal and never flagged here.
    # code_gen/debug answers are expected to be pure code (their repetition
    # signal is the dedicated consecutive-duplicate-lines rule), so the
    # prose sentence check only applies to natural-language task types.
    if ttype in {'qa', 'counterexample_020'} and has_sentence_loop(prose):
        reasons.append('prose sentence loop detected')

    if ttype in {'code_gen', 'debug'}:
        target = item.get('target_func', '')
        if not target:
            reasons.append('missing target_func')
        if not blocks:
            reasons.append('no fenced python code found')
        else:
            joined = '\n'.join(blocks)
            ok, err = is_valid_python(joined)
            if not ok:
                reasons.append(f'code syntax error: {err}')
            if has_consecutive_dup_lines(joined):
                reasons.append('code has >=3 consecutive identical lines')
            if target and blocks and ok and not defines_function(joined, target):
                reasons.append(f'target function {target} not defined in code')

    elif ttype == 'qa':
        for term in item.get('key_terms', []):
            if term not in answer:
                reasons.append(f'key term missing from answer: {term}')

    elif ttype == 'counterexample_019':
        ok, err = is_valid_python(answer)
        if not ok:
            reasons.append(f'answer is not valid python: {err}')
        if len(answer.strip()) > MAX_019_LEN:
            reasons.append(f'answer longer than {MAX_019_LEN} chars')

    elif ttype == 'counterexample_020':
        sentences = sum(answer.strip().count(e) for e in SENTENCE_ENDINGS)
        if sentences > 1:
            reasons.append(f'expected at most one sentence, found {sentences}')
        if len(answer.strip()) < MIN_020_LEN:
            reasons.append('one-sentence answer too short')
        if len(answer.strip()) > MAX_020_LEN:
            reasons.append(f'answer longer than {MAX_020_LEN} chars')

    return reasons


# ---------- schema + dedup ----------

def check_schema(item: dict) -> list[str]:
    reasons: list[str] = []
    required = ('source_id', 'rights', 'reviewed_by', 'split', 'task_type', 'messages', 'note')
    for key in required:
        if key not in item:
            reasons.append(f'missing field: {key}')
    if item.get('rights') != 'self_authored':
        reasons.append("rights must be 'self_authored'")
    if item.get('split') != 'train':
        reasons.append("candidate split must be 'train'")
    msgs = item.get('messages')
    if not isinstance(msgs, list) or len(msgs) != 2:
        reasons.append('messages must be a 2-item list')
    elif [m.get('role') for m in msgs] != ['user', 'assistant']:
        reasons.append('messages must be user then assistant')
    return reasons


def audit_candidates(records: list[dict]) -> dict:
    """Run the full rule audit; returns a report dict (no side effects)."""
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    approved: list[dict] = []
    rejected: list[dict] = []
    by_type: dict[str, dict[str, int]] = {}

    for item in records:
        reasons = check_schema(item)
        sid = item.get('source_id', '')
        if sid in seen_ids:
            reasons.append(f'duplicate source_id: {sid}')
        pair = tuple(m.get('content', '').strip()
                     for m in item.get('messages', [{}, {}]))
        if pair in seen_pairs:
            reasons.append('duplicate (question, answer) pair')
        if not reasons:
            reasons = check_record(item)
        if sid:
            seen_ids.add(sid)
        seen_pairs.add(pair)

        ttype = str(item.get('task_type'))
        bucket = by_type.setdefault(ttype, {'total': 0, 'approved': 0})
        bucket['total'] += 1
        if reasons:
            rejected.append({'source_id': sid, 'reasons': reasons})
        else:
            approved.append({**item, 'approved': True})
            bucket['approved'] += 1

    return {
        'total': len(records),
        'approved_count': len(approved),
        'rejected_count': len(rejected),
        'by_type': by_type,
        'approved': approved,
        'rejected': rejected,
    }


# ---------- leakage scan ----------

FUNC_IN_QUESTION = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(')

# Python builtins / ubiquitous helper names: they appear in almost every
# snippet, so counting them as "leakage" would flag everything.
_BUILTIN_NAMES = {
    'len', 'sum', 'print', 'range', 'max', 'min', 'abs', 'int', 'str', 'float',
    'bool', 'list', 'dict', 'set', 'sorted', 'enumerate', 'zip', 'any', 'all',
    'isinstance', 'getattr', 'dict_items', 'input',
}

# Dotted method calls like "target.append(item)" — the captured name is a
# method on some object, not a free function name, so never treat it as a
# task function for leakage purposes.
_METHOD_CALL = re.compile(r'\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(')


def _task_func_names(text: str) -> set[str]:
    """Free function-call names in the text, minus builtins and method calls."""
    text = str(text)
    method_pos = [m.start() for m in _METHOD_CALL.finditer(text)]
    names: set[str] = set()
    for m in FUNC_IN_QUESTION.finditer(text):
        # Skip calls that are dotted method calls (preceded by '.').
        prefix = text[max(0, m.start() - 1):m.start()]
        if prefix == '.':
            continue
        # Skip if this call position overlaps a captured method call span.
        if any(pos <= m.start() < pos + 1 for pos in method_pos):
            continue
        if m.group(1) not in _BUILTIN_NAMES:
            names.add(m.group(1))
    return names


def scan_eval_leakage(records: list[dict], eval_questions: list[str]) -> list[dict]:
    """Report candidates whose question mentions a custom function name that
    also appears in an eval question. Report-only: reviewers decide."""
    eval_names: set[str] = set()
    for q in eval_questions:
        eval_names.update(_task_func_names(q))
    flagged = []
    for item in records:
        names = _task_func_names(item.get('messages', [{}, {}])[0].get('content', ''))
        hit = sorted(names & eval_names)
        if hit:
            flagged.append({'source_id': item.get('source_id'), 'overlapping_names': hit})
    return flagged


# ---------- file IO ----------

def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()
            if line.strip()]


def write_jsonl(path: str | Path, records: list[dict]) -> None:
    Path(path).write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n',
        encoding='utf-8')
