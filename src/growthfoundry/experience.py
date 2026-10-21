"""Append-only verified-experience ledger with human approval at ingestion."""
import json
from datetime import datetime, timezone
from pathlib import Path


def record_experience(path: str | Path, *, task_id: str, lesson: str, test_evidence: str,
                      approved: bool = False) -> dict:
    if not task_id.strip() or not lesson.strip() or not test_evidence.strip():
        raise ValueError('task, lesson and evidence required')
    item = {
        'task_id':task_id, 'lesson':lesson, 'test_evidence':test_evidence,
        'approved_for_learning':bool(approved),
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'training_eligible':False,  # separate source and rights check required
    }
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a',encoding='utf-8') as f: f.write(json.dumps(item,ensure_ascii=False)+'\n')
    return item
