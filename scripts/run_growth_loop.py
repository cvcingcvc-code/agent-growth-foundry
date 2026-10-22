"""Unified growth-loop orchestrator: data gate -> train -> evaluate ->
coding execution regression -> promotion decision, with JSON evidence.

The loop encodes the project's growth mechanism in one place:
  1. data gate        : read_approved enforces rights/approval/split/dedup
  2. train            : scripts/train_lora.py (real GPU LoRA, BLOCKED without CUDA)
  3. evaluate         : scripts/eval_lora.py base-vs-adapter on the fixed eval set
  4. coding exec gate : scripts/eval_coding_exec.py REAL code execution on the
                        fixed 10-task regression set (candidate AND champion,
                        same base/template/sampling/tests); missing evidence
                        or inconsistent conditions -> HOLD
  5. regression gate  : growthfoundry.regression degeneration checks
  6. promotion decision: exec_gate.py execution-level judgment + PROMOTE/HOLD
     (PROMOTE is a suggestion pending human review, never auto-promotes)

Usage:
  python scripts/run_growth_loop.py --dataset data/seed/sft_examples_v3.jsonl \
      --adapter models/qwen3-0.6b-lora-v3b --prev-adapter models/qwen3-0.6b-lora-v0 \
      --epochs 1 --exec-policy reviewed
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from growthfoundry.dataset import read_approved
from growthfoundry.regression import check_sample, decide_promotion, summarize_checks
from growthfoundry.exec_gate import decide_promotion_exec_level, dataset_fingerprint


def step(name: str, payload: dict) -> None:
    print(json.dumps({'step': name, **payload}, ensure_ascii=False), flush=True)


def run_subprocess(cmd: list[str], env: dict | None = None, timeout_sec: int = 3600) -> dict:
    import os
    merged = {**os.environ, **(env or {})}
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=merged, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout_sec)
    return {'cmd': cmd, 'exit_code': proc.returncode,
            'stdout_tail': proc.stdout[-2000:], 'stderr_tail': proc.stderr[-2000:],
            'elapsed_sec': round(time.monotonic() - t0, 1)}


def load_training_report(adapter_dir: Path) -> dict:
    report = adapter_dir / 'training_report.json'
    if not report.exists():
        raise FileNotFoundError(f'missing training report: {report}')
    return json.loads(report.read_text(encoding='utf-8'))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', required=True)
    p.add_argument('--adapter', required=True, help='output adapter dir for this run')
    p.add_argument('--prev-adapter', required=True, help='previous promoted adapter dir (champion)')
    p.add_argument('--prev-report', default=None,
                   help='previous training_report.json (defaults to <prev-adapter>/training_report.json)')
    p.add_argument('--champion-file', default='data/champion.json',
                   help='champion registry; comparison target is the champion, not the latest run')
    p.add_argument('--champion-eval', default='outputs/base_vs_lora_eval.json',
                   help='champion per-sample eval evidence path')
    p.add_argument('--learning-rate', type=float, default=2e-4,
                   help='candidate training lr; never claim fixed optimal without comparison')
    p.add_argument('--history-file', default='data/model_history.jsonl',
                   help='append-only trend log of all runs')
    p.add_argument('--model', default='Qwen/Qwen3-0.6B')
    p.add_argument('--epochs', type=float, default=2)
    p.add_argument('--max-length', type=int, default=384)
    p.add_argument('--max-regressions', type=int, default=0,
                   help='tolerated new degenerated samples (0 = any regression blocks promotion)')
    p.add_argument('--train-timeout-sec', type=int, default=3600)
    p.add_argument('--python', default=sys.executable, help='python used for train/eval subprocesses')
    p.add_argument('--evidence-dir', default='data/reports/growth_loop')
    p.add_argument('--regression-set', default='data/eval/coding_regression_fixed.jsonl',
                   help='fixed 10-task coding regression set (execution-level gate)')
    p.add_argument('--exec-policy', default='reviewed', choices=('blocked', 'reviewed', 'harness'),
                   help='execution policy for the coding regression gate')
    p.add_argument('--skip-exec-gate', action='store_true',
                   help='skip the coding execution gate (rounds without execution evidence)')
    p.add_argument('--dry-run', action='store_true', help='gate data only, no training')
    a = p.parse_args()

    run_id = f'growth-loop-{time.strftime("%Y%m%d-%H%M%S")}'
    evidence = Path(a.evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: data gate -------------------------------------------------
    try:
        splits = read_approved(a.dataset)
    except Exception as ex:
        step('data_gate', {'status': 'BLOCKED', 'error': str(ex)})
        print(json.dumps({'run_id': run_id, 'final': 'BLOCKED_DATA_GATE'}, ensure_ascii=False))
        return
    step('data_gate', {'status': 'PASS', 'train': len(splits['train']), 'eval': len(splits['eval'])})
    if a.dry_run:
        print(json.dumps({'run_id': run_id, 'final': 'DRY_RUN_STOP'}, ensure_ascii=False))
        return

    # ---- Step 2: train (real GPU LoRA; subprocess enforces timeout) --------
    train_cmd = [a.python, 'scripts/train_lora.py', '--dataset', a.dataset,
                 '--output', a.adapter, '--epochs', str(a.epochs),
                 '--learning-rate', str(a.learning_rate), '--max-length', str(a.max_length)]
    train_res = run_subprocess(train_cmd, timeout_sec=a.train_timeout_sec)
    (evidence / f'{run_id}-train.json').write_text(
        json.dumps(train_res, ensure_ascii=False, indent=2), encoding='utf-8')
    if train_res['exit_code'] != 0:
        step('train', {'status': 'FAILED', 'exit_code': train_res['exit_code']})
        print(json.dumps({'run_id': run_id, 'final': 'FAILED_TRAINING'}, ensure_ascii=False))
        return
    report = load_training_report(ROOT / a.adapter)
    step('train', {'status': 'FINISHED', 'train_loss': report.get('train_loss'),
                   'eval_loss': report.get('eval_loss'), 'elapsed_sec': train_res['elapsed_sec']})

    # ---- Step 3: evaluate base-vs-adapter on the fixed eval set ------------
    eval_out = f'outputs/base_vs_lora_eval_{Path(a.adapter).name}.json'
    eval_cmd = [a.python, 'scripts/eval_lora.py', '--dataset', a.dataset,
                '--adapter', a.adapter, '--output', eval_out]
    eval_res = run_subprocess(eval_cmd, timeout_sec=a.train_timeout_sec)
    (evidence / f'{run_id}-eval.json').write_text(
        json.dumps(eval_res, ensure_ascii=False, indent=2), encoding='utf-8')
    if eval_res['exit_code'] != 0:
        step('evaluate', {'status': 'FAILED', 'exit_code': eval_res['exit_code']})
        print(json.dumps({'run_id': run_id, 'final': 'FAILED_EVALUATION'}, ensure_ascii=False))
        return
    eval_path = ROOT / eval_out
    eval_data = json.loads(eval_path.read_text(encoding='utf-8'))
    step('evaluate', {'status': 'FINISHED', 'samples': eval_data.get('samples'), 'output': eval_out})

    # ---- Step 3.5: coding execution gate (REAL execution, Round 4.1) -------
    # Both candidate and champion run the SAME fixed 10-task regression set
    # with the same base/template/sampling/tests. Real code execution via the
    # restricted runner. Missing/inconsistent evidence -> HOLD.
    exec_decision = None
    if not a.skip_exec_gate:
        from growthfoundry.champion import load_champion as _load_champion
        _champ = _load_champion(ROOT / a.champion_file) if (ROOT / a.champion_file).exists() else None
        champ_regression_path = ROOT / 'outputs' / 'coding_exec_champion_baseline.json'
        if _champ is None:
            step('exec_gate', {'status': 'HOLD', 'reason': 'no champion registered'})
            print(json.dumps({'run_id': run_id, 'final': 'HOLD_NO_CHAMPION'}, ensure_ascii=False))
            return
        if not champ_regression_path.exists():
            step('exec_gate', {'status': 'HOLD',
                               'reason': f'missing champion execution baseline: {champ_regression_path}',
                               'note': 'run scripts/eval_coding_exec.py --adapter <champion> first'})
            print(json.dumps({'run_id': run_id, 'final': 'HOLD_EXEC_EVIDENCE_MISSING'}, ensure_ascii=False))
            return

        cand_exec_out = f'outputs/coding_exec_{Path(a.adapter).name}.json'
        cand_exec_cmd = [a.python, 'scripts/eval_coding_exec.py',
                         '--adapter', a.adapter, '--model', a.model,
                         '--regression-set', a.regression_set,
                         '--exec-policy', a.exec_policy,
                         '--output', cand_exec_out]
        cand_exec_res = run_subprocess(cand_exec_cmd, timeout_sec=a.train_timeout_sec)
        (evidence / f'{run_id}-exec.json').write_text(
            json.dumps(cand_exec_res, ensure_ascii=False, indent=2), encoding='utf-8')
        if cand_exec_res['exit_code'] != 0:
            step('exec_gate', {'status': 'FAILED', 'exit_code': cand_exec_res['exit_code']})
            print(json.dumps({'run_id': run_id, 'final': 'FAILED_EXEC_GATE'}, ensure_ascii=False))
            return
        cand_exec = json.loads((ROOT / cand_exec_out).read_text(encoding='utf-8'))
        champ_exec = json.loads(champ_regression_path.read_text(encoding='utf-8'))

        # Sampling/config metadata for consistency checks.
        cand_run_meta = {**cand_exec.get('sampling', {}),
                         'base_model': cand_exec.get('base_model', a.model),
                         'test_hint_hash': cand_exec.get('test_hint_hash'),
                         'prompt_template': cand_exec.get('prompt_template')}
        champ_run_meta = {**champ_exec.get('sampling', {}),
                          'base_model': champ_exec.get('base_model'),
                          'test_hint_hash': champ_exec.get('test_hint_hash'),
                          'prompt_template': champ_exec.get('prompt_template')}

        exec_decision = decide_promotion_exec_level(
            {**cand_run_meta, 'results': cand_exec.get('results', [])},
            {**champ_run_meta, 'results': champ_exec.get('results', [])})
        step('exec_gate', {'status': exec_decision['decision'],
                           'reasons': exec_decision['reasons'],
                           'candidate_pass_rate': exec_decision.get('candidate_pass_rate'),
                           'champion_pass_rate': exec_decision.get('champion_pass_rate'),
                           'regressions': exec_decision.get('regressions'),
                           'candidate_output': cand_exec_out})
        if exec_decision['decision'] == 'HOLD':
            (evidence / f'{run_id}-decision.json').write_text(
                json.dumps({'run_id': run_id, 'decision': 'HOLD', 'gate': 'exec_gate',
                            'reasons': exec_decision['reasons'], 'champion_changed': False},
                           ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'run_id': run_id, 'final': 'HOLD_EXEC_GATE',
                              'reasons': exec_decision['reasons']}, ensure_ascii=False))
            return
    else:
        step('exec_gate', {'status': 'SKIPPED', 'note': '--skip-exec-gate set'})

    # ---- Step 4: regression gate vs the CURRENT CHAMPION --------------------
    # The champion is the promoted version, never the latest run. Comparison
    # must use the champion's own per-sample eval evidence (same data/template/
    # sampling config). Missing evidence -> conservative HOLD.
    from growthfoundry.champion import (champion_comparison_ready, load_champion,
                                        append_history, build_promotion_suggestion)
    champion = load_champion(ROOT / a.champion_file) if (ROOT / a.champion_file).exists() else None
    # Anti-bypass (round-4.1 Task 3): the champion evidence must be intact
    # AND recorded for the SAME dataset the candidate ran on. A different
    # dataset or an empty/{} evidence file can no longer pass the gate.
    from eval_lora import dataset_sha256_of
    dataset_sha = dataset_sha256_of(ROOT / a.dataset)
    ready, ready_reason = champion_comparison_ready(champion, ROOT / a.champion_eval,
                                                    expected_samples=2,
                                                    expected_dataset_sha256=dataset_sha)
    if not ready:
        step('champion_gate', {'status': 'HOLD', 'reason': ready_reason,
                               'note': 'candidate runs must compare against the champion; '
                                       'missing/intact evidence checks are enforced (round-4.1)'})
        print(json.dumps({'run_id': run_id, 'final': 'HOLD_CHAMPION_EVIDENCE_MISSING'}, ensure_ascii=False))
        return
    champion_eval_path = ROOT / a.champion_eval

    new_checks, old_checks = [], []
    for item in eval_data['items']:
        new_checks.append(check_sample(item['source_id'], item['lora_answer'], item['reference_answer']))
    # champion per-sample evidence is the comparison baseline (old_checks)
    prev_report_path = Path(a.prev_report) if a.prev_report else ROOT / a.prev_adapter / 'training_report.json'
    if not prev_report_path.exists():
        step('regression_gate', {'status': 'HOLD', 'error': f'missing champion training report: {prev_report_path}',
                                 'note': 'champion metrics required for loss comparison'})
        print(json.dumps({'run_id': run_id, 'final': 'HOLD_NO_PREVIOUS_EVIDENCE'}, ensure_ascii=False))
        return
    champion_data = json.loads(champion_eval_path.read_text(encoding='utf-8'))
    for item in champion_data['items']:
        old_checks.append(check_sample(item['source_id'], item['lora_answer'], item['reference_answer']))
    step('regression_gate', {'new': summarize_checks(new_checks), 'champion': summarize_checks(old_checks),
                             'champion_adapter': champion.adapter})

    # ---- Step 5: promotion suggestion vs champion (AGENTS.md rule 7) --------
    # PROMOTE is a suggestion pending human review; champion pointer never
    # auto-rotates. All runs are appended to history for trend analysis.
    champion_report = load_training_report(ROOT / a.prev_adapter) if (ROOT / a.prev_adapter) else None
    decision = decide_promotion(report, champion_report or report,
                                new_checks, old_checks, max_regressions=a.max_regressions)
    # Exec-level gate already PROMOTEd; keep the stricter of the two verdicts.
    if exec_decision is not None and exec_decision['decision'] == 'PROMOTE':
        decision_reasons = decision.reasons + ['exec-gate: ' + r for r in exec_decision['reasons']]
        final_decision = 'PROMOTE'
        final_regressions = decision.new_degenerated
    else:
        decision_reasons = decision.reasons
        final_decision = decision.decision
        final_regressions = decision.new_degenerated
    suggestion = build_promotion_suggestion(final_decision, decision_reasons, a.adapter, champion.adapter)
    verdict = {
        'run_id': run_id,
        'dataset': a.dataset,
        'candidate_adapter': a.adapter,
        'champion_adapter': champion.adapter,
        'comparison_target': 'champion (promoted version)',
        'candidate_metrics': {'train_loss': report.get('train_loss'), 'eval_loss': report.get('eval_loss'),
                              'epochs': report.get('epochs'), 'learning_rate': report.get('learning_rate')},
        'champion_metrics': {'eval_loss': champion.eval_loss},
        'decision': final_decision,
        'reasons': decision_reasons,
        'new_degenerated': final_regressions,
        'champion_degenerated': decision.old_degenerated,
        'exec_gate': exec_decision if exec_decision is not None else 'skipped',
        'promotion_note': 'PROMOTE is a suggestion pending human review; champion pointer changes only after explicit human approval.',
        'pending_human_review': suggestion['pending_human_review'],
        'champion_changed': False,
    }
    (evidence / f'{run_id}-decision.json').write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2), encoding='utf-8')
    append_history(ROOT / a.history_file, {
        'run_id': run_id, 'candidate': a.adapter, 'champion': champion.adapter,
        'dataset': a.dataset, 'epochs': a.epochs, 'learning_rate': a.learning_rate,
        'candidate_eval_loss': report.get('eval_loss'), 'champion_eval_loss': champion.eval_loss,
        'decision': final_decision, 'new_degenerated': final_regressions,
        'exec_gate_decision': exec_decision['decision'] if exec_decision else 'skipped',
    })
    step('promotion_decision', verdict)
    print(json.dumps({'run_id': run_id, 'final': final_decision,
                      'pending_human_review': suggestion['pending_human_review']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
