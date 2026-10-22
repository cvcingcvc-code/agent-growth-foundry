"""Champion registry: the permanent champion is the PROMOTED version, never
the most recently trained one.

Rules (AGENTS.md rule 7 / INTERFACES.md version policy):
- The champion file records the currently usable adapter, its evidence paths
  and the human approval record.
- Every candidate must be compared against the CURRENT champion under the
  same data/template/sampling configuration.
- When champion per-sample evaluation evidence is missing: conservative HOLD.
- History of all runs is append-only (model_history.jsonl) for trend analysis;
  champion records are never overwritten by later runs.
- A PROMOTE suggestion only marks 'pending_human_review'; the champion pointer
  changes only after explicit human approval (champion.py never auto-rotates).
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# adapter family compatibility: adapter trained on one base must never be
# mounted onto an incompatible base; switching base = new model series.
_FAMILY_RE = re.compile(r'^(?P<family>[A-Za-z0-9_.-]+?)(?:-(?P<size>\d+(?:\.\d+)?[bB]))?(?:-(?P<rest>.+))?$')


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Champion:
    adapter: str
    base_model: str
    promoted_at: str
    approved_by: str
    eval_loss: float
    evidence: list[str]


def load_champion(path: str | Path) -> Champion | None:
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding='utf-8'))
    for key in ('adapter', 'base_model', 'promoted_at', 'approved_by', 'eval_loss'):
        if key not in data:
            raise ValueError(f'champion file missing field: {key}')
    return Champion(adapter=data['adapter'], base_model=data['base_model'],
                    promoted_at=data['promoted_at'], approved_by=data['approved_by'],
                    eval_loss=float(data['eval_loss']), evidence=list(data.get('evidence', [])))


def save_champion(path: str | Path, champion: Champion) -> None:
    """Explicit human-approval write; call only after a reviewed promotion."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {'adapter': champion.adapter, 'base_model': champion.base_model,
               'promoted_at': champion.promoted_at, 'approved_by': champion.approved_by,
               'eval_loss': champion.eval_loss, 'evidence': champion.evidence}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def append_history(path: str | Path, record: dict) -> None:
    """Append-only trend record; never overwrites existing lines."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    item = {'recorded_at': now(), **record}
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(item, ensure_ascii=False) + '\n')


def base_family(model_id: str) -> str:
    """Model family of a base id: 'Qwen/Qwen3-0.6B' -> 'Qwen/Qwen3';
    'Qwen/Qwen3-Coder-30B' -> 'Qwen/Qwen3-Coder' (a different series from Qwen3)."""
    prefix = model_id.split('/')[0] + '/' if '/' in model_id else ''
    name = model_id.split('/')[-1] if '/' in model_id else model_id
    # strip trailing size suffix like -0.6B / -30B / -1.7B
    name = re.sub(r'-\d+(?:\.\d+)?[bB]$', '', name)
    return prefix + name


def adapter_base_compatible(adapter_config: dict, target_base: str) -> bool:
    """Adapter must be mounted onto the EXACT same base it was trained on.

    A 0.6B adapter carries weight dimensions learned for that specific base;
    same-family larger bases (Qwen3-4B/8B) or different series (Qwen3-Coder)
    are all incompatible. Switching base = new model series, retrain + re-accept.
    """
    adapter_base = (adapter_config.get('base_model')
                    or adapter_config.get('base_model_name_or_path')
                    or adapter_config.get('_name_or_path') or '')
    if not adapter_base:
        return False  # unknown provenance: incompatible by default
    # normalize: strip trailing slash artifacts, compare exact ids
    norm = lambda s: str(s).replace('\\', '/').rstrip('/')
    return norm(adapter_base) == norm(target_base)


def champion_comparison_ready(champion: Champion | None, champion_eval_path: str | Path | None,
                              expected_samples: int | None = None,
                              expected_dataset_sha256: str | None = None) -> tuple[bool, str]:
    """Conservative gate (round-4.1 hardened): comparison requires a champion
    AND intact per-sample eval evidence; anything unverifiable -> HOLD.

    Anti-bypass checks:
    - champion registered (else HOLD);
    - evidence file exists and is valid JSON with an 'items' list (an empty
      file or '{}' no longer passes);
    - evidence holds at least expected_samples records (default: >=2);
    - when expected_dataset_sha256 is given, the evidence must carry a
      matching dataset fingerprint (same dataset as the candidate run), so a
      different dataset cannot sneak past the regression gate.
    """
    if champion is None:
        return False, 'no champion registered; register v0 with evidence before candidate runs'
    if champion_eval_path is None or not Path(champion_eval_path).exists():
        return False, f'champion per-sample eval evidence missing: {champion_eval_path}; conservative HOLD'
    try:
        data = json.loads(Path(champion_eval_path).read_text(encoding='utf-8'))
    except Exception as ex:
        return False, f'champion eval evidence unreadable: {type(ex).__name__}; conservative HOLD'
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return False, ('champion eval evidence has no per-sample items; '
                       'surface-only or empty evidence cannot anchor a comparison; conservative HOLD')
    min_needed = expected_samples if expected_samples is not None else 2
    if len(items) < min_needed:
        return False, (f'champion eval evidence has {len(items)} samples, need >= {min_needed}; '
                       'conservative HOLD')
    if expected_dataset_sha256 is not None:
        fp = data.get('dataset_fingerprint') or {}
        if fp.get('sha256') != expected_dataset_sha256:
            return False, ('champion eval evidence dataset fingerprint mismatch '
                           f'(expected {expected_dataset_sha256[:12]}…, got {str(fp.get("sha256"))[:12]}…); '
                           'a different dataset must not bypass the regression gate; conservative HOLD')
    return True, 'champion and intact evidence present'


def build_promotion_suggestion(decision: str, reasons: list[str], candidate: str,
                               champion_adapter: str) -> dict:
    """PROMOTE is only a suggestion pending human review; never auto-rotates."""
    return {
        'decision': decision,
        'reasons': reasons,
        'candidate_adapter': candidate,
        'champion_adapter': champion_adapter,
        'pending_human_review': decision == 'PROMOTE',
        'champion_changed': False,  # champion.py never auto-rotates the pointer
    }
