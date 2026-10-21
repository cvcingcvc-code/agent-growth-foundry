"""Rule-based audit for candidate training samples (round-4 coding pool).

Checks every candidate in the pool against:
1. Schema: required fields, rights=self_authored, split=train, 2-message format.
2. Per-type rules:
   - code_gen/debug: fenced code parses (ast), defines target function,
     no >=3 consecutive identical lines (code equivalent of sft-020 loop).
   - qa: every declared key term appears in the answer.
   - counterexample_019: answer itself is valid python, length <= 80
     (anti off-topic, sft-019 counter-rule).
   - counterexample_020: at most one sentence, 10..80 chars
     (anti repetition loop, sft-020 counter-rule).
3. Dedup: unique source_id, unique (question, answer) pair.
4. Prose repetition loop scan (the sft-020 failure mode).
5. Eval leakage scan (report-only): function names shared with the
   coding_eval_v1 holdout.

Only records with zero failure reasons are written to the approved pool.
The audit is deliberately conservative: anything it cannot verify is
rejected with an explicit reason.

Run:
  python scripts/audit_candidates.py \
      --candidates data/seed/coding_candidates_v1.jsonl \
      --eval-set data/eval/coding_eval_v1.jsonl \
      --approved-out data/seed/coding_approved_v1.jsonl \
      --report outputs/audit_candidates_v1.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.candidate_audit import (
    audit_candidates, read_jsonl, scan_eval_leakage, write_jsonl,
)


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', required=True)
    parser.add_argument('--eval-set', default='data/eval/coding_eval_v1.jsonl')
    parser.add_argument('--approved-out', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()

    records = read_jsonl(args.candidates)
    eval_records = read_jsonl(args.eval_set)
    eval_questions = [r.get('question', '') for r in eval_records]

    report = audit_candidates(records)
    leakage = scan_eval_leakage(records, eval_questions)

    approved = report.pop('approved')
    rejected = report.pop('rejected')

    write_jsonl(args.approved_out, approved)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps({
        'status': 'AUDIT_RULES_PASS' if not rejected else 'AUDIT_REJECTED_PRESENT',
        'candidates_file': args.candidates,
        'candidates_sha256': sha256_file(args.candidates),
        'eval_set': args.eval_set,
        'audit': report,
        'leakage_scan': {
            'method': 'function-name overlap with eval questions (report-only)',
            'flagged': leakage,
        },
        'rejected': rejected,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({
        'status': 'AUDIT_RULES_PASS' if not rejected else 'AUDIT_REJECTED_PRESENT',
        'total': report['total'],
        'approved': report['approved_count'],
        'rejected': report['rejected_count'],
        'by_type': report['by_type'],
        'leakage_flagged': len(leakage),
        'approved_out': args.approved_out,
        'report': args.report,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
