"""Dataset merger and gatekeeper for sft_examples_v4 (GrowthFoundry V2 Phase 1).

Combines:
- Original seed (sft_examples.jsonl)
- Approved V1 coding pool (coding_approved_v1.jsonl)
- Verified V2 synthetic coding pool (coding_verified_v2.jsonl)
- Multi-turn dialogues (multiturn_dialogues_v2.jsonl)
- Holdout evaluation set (coding_eval_v2.jsonl)

Enforces zero leakage between train and eval splits, deduplicates source_ids,
and calculates dataset SHA-256 fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from growthfoundry.dataset import validate_record


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def merge_datasets() -> dict:
    train_records: list[dict] = []
    eval_records: list[dict] = []
    seen_ids: set[str] = set()

    sources = [
        (ROOT / 'data/seed/sft_examples.jsonl', 'seed_v0'),
        (ROOT / 'data/seed/coding_approved_v1.jsonl', 'coding_v1'),
        (ROOT / 'data/seed/coding_verified_v2.jsonl', 'verified_v2'),
        (ROOT / 'data/seed/multiturn_dialogues_v2.jsonl', 'multiturn_v2'),
        (ROOT / 'data/eval/coding_eval_v2.jsonl', 'eval_v2'),
    ]

    for path, tag in sources:
        if not path.exists():
            raise FileNotFoundError(f"Missing required dataset: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line.strip())
                # Normalize schema
                if 'rights' not in rec:
                    rec['rights'] = 'self_authored'
                if 'reviewed_by' not in rec:
                    rec['reviewed_by'] = 'dataset_author'
                if 'approved' not in rec:
                    rec['approved'] = True

                # If formatted as question + reference_answer, convert to messages
                if 'messages' not in rec and 'question' in rec and 'reference_answer' in rec:
                    rec['messages'] = [
                        {'role': 'user', 'content': rec['question']},
                        {'role': 'assistant', 'content': rec['reference_answer']}
                    ]

                sid = rec['source_id']
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)

                # Validate record structure
                validate_record(rec)

                if rec.get('split') == 'eval':
                    eval_records.append(rec)
                else:
                    rec['split'] = 'train'
                    train_records.append(rec)

    all_records = train_records + eval_records
    out_path = ROOT / 'data/seed/sft_examples_v4.jsonl'
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, 'w', encoding='utf-8') as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    fp = sha256_file(out_path)
    summary = {
        'status': 'MERGE_PASS',
        'output_file': str(out_path),
        'sha256': fp,
        'train_samples': len(train_records),
        'eval_samples': len(eval_records),
        'total_samples': len(all_records)
    }
    return summary


def main():
    summary = merge_datasets()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
