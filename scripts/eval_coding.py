"""Evaluate a model (base or adapter) on the coding eval set with a UNIFIED
sampling configuration (greedy, fixed max-new-tokens) so base-vs-adapter
comparisons are fair. Produces per-sample answers + code metrics summary.

Usage:
  python scripts/eval_coding.py --adapter models/qwen3-0.6b-lora-v0 \
      --eval-set data/eval/coding_eval_v1.jsonl --limit 10 \
      --output outputs/coding_eval_v0_baseline.json
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
from chat_local import generate_once, load_model_and_tokenizer  # noqa: E402
from growthfoundry.code_metrics import summarize  # noqa: E402


def build_eval_report(records, answers, adapter_label, sampling, elapsed_sec):
    """Assemble the per-sample coding eval structure (pure, testable)."""
    assert len(records) == len(answers), 'length mismatch'
    items = []
    for rec, ans in zip(records, answers):
        items.append({
            'source_id': rec['source_id'],
            'task_type': rec.get('task_type', 'unknown'),
            'question': rec['question'],
            'reference_answer': rec.get('reference_answer', ''),
            'model_answer': ans,
        })
    return {
        'status': 'CODING_EVAL_SAMPLE_LEVEL_EVIDENCE',
        'adapter': adapter_label,
        'sampling': sampling,
        'samples': len(items),
        'elapsed_sec': elapsed_sec,
        'items': items,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--eval-set', default='data/eval/coding_eval_v1.jsonl')
    p.add_argument('--model', default='Qwen/Qwen3-0.6B')
    p.add_argument('--adapter', default='none', help='adapter dir or "none" for raw base')
    p.add_argument('--output', required=True)
    p.add_argument('--limit', type=int, default=0, help='evaluate first N tasks (0 = all)')
    p.add_argument('--max-new-tokens', type=int, default=224)
    p.add_argument('--timeout-sec', type=int, default=90)
    a = p.parse_args()

    lines = [json.loads(l) for l in Path(a.eval_set).read_text(encoding='utf-8').splitlines() if l.strip()]
    if a.limit > 0:
        lines = lines[:a.limit]
    print(json.dumps({'eval_tasks': len(lines), 'adapter': a.adapter}, ensure_ascii=False), flush=True)

    model, tokenizer = load_model_and_tokenizer(a.model, a.adapter)
    answers, t0 = [], time.monotonic()
    for i, rec in enumerate(lines, 1):
        res = generate_once(model, tokenizer, rec['question'], a.max_new_tokens, a.timeout_sec)
        answers.append(res['text'] if not res['error'] else f"[GENERATION_ERROR] {res['error']}")
        if i % 5 == 0 or i == len(lines):
            print(json.dumps({'progress': f'{i}/{len(lines)}'}, ensure_ascii=False), flush=True)
    elapsed = round(time.monotonic() - t0, 1)

    sampling = {'mode': 'greedy', 'max_new_tokens': a.max_new_tokens, 'timeout_sec': a.timeout_sec}
    report = build_eval_report(lines, answers, a.adapter, sampling, elapsed)
    # unified metrics on the same answers
    report['metrics'] = summarize(answers, [r.get('reference_answer', '') for r in lines])
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'saved': str(out), 'metrics': report['metrics']['syntax']['rate'],
                      'repetition_rate': report['metrics']['repetition']['rate'],
                      'relevance_rate': report['metrics']['relevance']['rate']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
