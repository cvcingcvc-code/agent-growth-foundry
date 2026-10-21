"""Offline candidate intake only. No copying code or auto publishing."""
import json
from pathlib import Path
from .policy import assess_license
from .store import Store


def run_candidates(inbox: Path, db_path: Path, report_path: Path) -> dict:
    store = Store(db_path)
    rows = []
    for n, line in enumerate(inbox.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        required = {"id", "title", "license", "source_url"}
        if not required <= set(item):
            raise ValueError(f"line {n}: missing fields {required-set(item)}")
        verdict = assess_license(item["license"], asset_rights_verified=item.get("assets_checked") is True)
        store.put(item, verdict.status, verdict.reason)
        rows.append({"candidate_id": item["id"], "state": verdict.status, "reason": verdict.reason})
    result = {"count": len(rows), "items": rows, "publish_enabled": False}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    store.close()
    return result
