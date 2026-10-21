"""Explicit-provenance data gate for supervised fine-tuning."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable

ACCEPTED_RIGHTS = {"self_authored", "explicit_training_permission", "licensed_for_training"}


def validate_record(item: dict) -> None:
    if not isinstance(item, dict):
        raise ValueError("record must be JSON object")
    if item.get("approved") is not True:
        raise ValueError("record not approved")
    if item.get("rights") not in ACCEPTED_RIGHTS:
        raise ValueError("missing training rights evidence")
    if item.get("split") not in {"train", "eval"}:
        raise ValueError("split must be train/eval")
    if not item.get("source_id") or not item.get("reviewed_by"):
        raise ValueError("source_id and reviewed_by required")
    msgs = item.get("messages")
    if not isinstance(msgs, list) or len(msgs) != 2:
        raise ValueError("two-message user/assistant conversation required")
    if [m.get("role") for m in msgs] != ["user", "assistant"]:
        raise ValueError("expected user followed by assistant")
    for m in msgs:
        if not isinstance(m.get("content"), str) or len(m["content"].strip()) < 6:
            raise ValueError("empty or insufficient content")


def read_approved(path: str | Path) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {"train": [], "eval": []}
    seen = set()
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            validate_record(item)
        except Exception as ex:
            raise ValueError(f"{path}:{line_no}: {ex}") from ex
        key = (item["messages"][0]["content"].strip(), item["messages"][1]["content"].strip())
        if key in seen:
            raise ValueError(f"duplicate train/eval record at line {line_no}")
        seen.add(key)
        result[item["split"]].append(item)
    if len(result["train"]) < 4 or len(result["eval"]) < 2:
        raise ValueError("insufficient approved split samples (need >=4 train and >=2 eval)")
    return result
