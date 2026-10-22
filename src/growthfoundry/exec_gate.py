"""Execution-level promotion gate (Round 4.1 Task 2).

The growth loop's promotion decision is based on REAL code execution on a
fixed regression set, not on eval_loss or surface metrics.

Judgment rules (strict):
- Execution evidence missing for candidate or champion -> HOLD.
- Eval set / sampling conditions differ between the two runs -> HOLD.
- Candidate introduces a NEW key-logic regression (task the champion passed
  but the candidate fails) -> HOLD.
- Candidate reaches the non-degeneration bar -> PROMOTE suggestion only
  (pending human review; never auto-promotes).

Evidence saved per task: code, assertions (test_hint), run result, failure
reason, dataset hashes. Pure decision logic is separated from IO so the whole
gate is testable without a GPU.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

GATE_VERSION = 'exec-gate-v1'


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()


def dataset_fingerprint(path: str | Path) -> dict:
    """SHA-256 of the dataset file + record count + id list, for
    consistency checks between candidate/champion runs."""
    p = Path(path)
    if not p.exists():
        return {'exists': False}
    records = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    return {
        'exists': True,
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
        'count': len(records),
        'ids': sorted(r.get('source_id', '') for r in records),
    }


def conditions_consistent(cand_run: dict, champ_run: dict) -> tuple[bool, list[str]]:
    """Both runs must use the same base, template, sampling, tasks and tests."""
    problems: list[str] = []
    if cand_run.get('base_model') != champ_run.get('base_model'):
        problems.append(f"base model differs: {cand_run.get('base_model')} vs {champ_run.get('base_model')}")
    if cand_run.get('test_hint_hash') != champ_run.get('test_hint_hash'):
        problems.append('task/test-hint set differs between runs')
    if cand_run.get('prompt_template') != champ_run.get('prompt_template'):
        problems.append('input template differs between runs')
    for key in ('sampling_mode', 'max_new_tokens'):
        if cand_run.get(key) != champ_run.get(key):
            problems.append(f'{key} differs: {cand_run.get(key)} vs {champ_run.get(key)}')
    return not problems, problems


def _normalized_items(run: dict) -> dict[str, dict]:
    """source_id -> {passed, failure} map from a regression-run record."""
    items = {}
    for item in run.get('results', []):
        items[item['source_id']] = {
            'passed': bool(item.get('passed')),
            'failure': item.get('failure', 'none'),
            'executed': bool(item.get('executed', item.get('passed'))),
        }
    return items


def decide_promotion_exec_level(cand_run: dict, champ_run: dict,
                                min_pass_rate: float = 0.6) -> dict:
    """Execution-level promotion decision. Never auto-promotes."""
    reasons: list[str] = []

    # Rule 1: execution evidence must exist on both sides.
    cand_items = _normalized_items(cand_run)
    champ_items = _normalized_items(champ_run)
    if not cand_items or not all(i['executed'] for i in cand_items.values()):
        missing = [sid for sid, i in cand_items.items() if not i['executed']] or ['(no per-task results)']
        return {'decision': 'HOLD', 'reasons': ['candidate execution evidence missing: '
                 + ', '.join(missing[:5])], 'gate_version': GATE_VERSION}
    if not champ_items or not all(i['executed'] for i in champ_items.values()):
        missing = [sid for sid, i in champ_items.items() if not i['executed']] or ['(no per-task results)']
        return {'decision': 'HOLD', 'reasons': ['champion execution evidence missing: '
                 + ', '.join(missing[:5])], 'gate_version': GATE_VERSION}

    # Rule 2: identical conditions.
    ok, problems = conditions_consistent(cand_run, champ_run)
    if not ok:
        return {'decision': 'HOLD', 'reasons': ['inconsistent eval conditions: ' + '; '.join(problems)],
                'gate_version': GATE_VERSION}

    # Rule 3: no NEW key-logic regression.
    regressions = [sid for sid, ci in cand_items.items()
                   if champ_items.get(sid, {}).get('passed') and not ci['passed']]
    if regressions:
        return {'decision': 'HOLD',
                'reasons': [f'new key-logic regression on {len(regressions)} task(s): '
                            + ', '.join(sorted(regressions)[:5])],
                'gate_version': GATE_VERSION, 'regressions': sorted(regressions)}

    # Rule 4: non-degeneration bar -> PROMOTE suggestion.
    cand_passed = sum(1 for i in cand_items.values() if i['passed'])
    cand_rate = cand_passed / len(cand_items)
    champ_passed = sum(1 for i in champ_items.values() if i['passed'])
    if cand_rate >= min_pass_rate:
        return {'decision': 'PROMOTE',
                'reasons': [f'execution pass rate {cand_passed}/{len(cand_items)} '
                            f'({round(cand_rate, 2)}) >= bar {min_pass_rate}; '
                            f'no new regression (champion {champ_passed}/{len(champ_items)})'],
                'pending_human_review': True, 'champion_changed': False,
                'gate_version': GATE_VERSION,
                'candidate_pass_rate': round(cand_rate, 4),
                'champion_pass_rate': round(champ_passed / len(champ_items), 4) if champ_items else 0.0}
    return {'decision': 'HOLD',
            'reasons': [f'execution pass rate {cand_passed}/{len(cand_items)} '
                        f'({round(cand_rate, 2)}) below bar {min_pass_rate}'],
            'gate_version': GATE_VERSION,
            'candidate_pass_rate': round(cand_rate, 4),
            'champion_pass_rate': round(champ_passed / len(champ_items), 4) if champ_items else 0.0}


def save_exec_evidence(out_path: str | Path, cand_run: dict, champ_run: dict,
                       cand_dataset: str | Path, champ_dataset: str | Path) -> dict:
    """Assemble and save the full execution-evidence bundle."""
    decision = decide_promotion_exec_level(cand_run, champ_run)
    cand_items = _normalized_items(cand_run)
    champ_items = _normalized_items(champ_run)
    bundle = {
        'gate_version': GATE_VERSION,
        'decision': decision,
        'consistency': {
            'candidate_dataset': dataset_fingerprint(cand_dataset),
            'champion_dataset': dataset_fingerprint(champ_dataset),
        },
        'candidate_run': {k: v for k, v in cand_run.items() if k != 'results'},
        'champion_run': {k: v for k, v in champ_run.items() if k != 'results'},
        'per_task': [
            {'source_id': sid,
             'candidate': cand_items[sid],
             'champion': champ_items.get(sid, {'passed': None, 'failure': 'not_in_set'})}
            for sid in sorted(cand_items)
        ],
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(bundle, ensure_ascii=False, indent=2),
                              encoding='utf-8')
    return bundle
