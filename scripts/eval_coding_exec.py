"""Execution-level coding regression evaluator (Round 4.1 Task 2).

Generates answers on the fixed 10-task regression set and executes them for
real (restricted runner). Records per-task: code, assertions (test_hint),
run result, failure reason. Saves a test_hint hash so the gate can verify
candidate and champion used the same tasks/tests.

Usage:
  python scripts/eval_coding_exec.py --adapter models/qwen3-0.6b-lora-v0 \
      --model Qwen/Qwen3-0.6B --regression-set data/eval/coding_regression_fixed.jsonl \
      --exec-policy reviewed --output outputs/coding_exec_champion_baseline.json
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
from growthfoundry.candidate_audit import has_consecutive_dup_lines, has_sentence_loop  # noqa: E402
from growthfoundry.code_metrics import extract_code_blocks, is_valid_python  # noqa: E402
from growthfoundry.sandbox_runner import run_restricted, security_report  # noqa: E402


def build_exec_runner(code: str, hint: str) -> str:
    from growthfoundry.sandbox_runner import build_guarded_runner
    return build_guarded_runner(code, hint)


def exec_one_task(model, tokenizer, rec: dict, max_new_tokens: int,
                  timeout_gen: int, timeout_exec: int, exec_policy: str,
                  prompt_template: str) -> dict:
    """One regression task: generate + real execution; full evidence."""
    question = rec['question']
    hint = rec.get('test_hint', '')
    t0 = time.time()

    res = generate_once(model, tokenizer, prompt_template.format(question=question),
                        max_new_tokens, timeout_gen)
    answer = res.get('text', '')
    blocks = extract_code_blocks(answer)
    code = '\n\n'.join(blocks)

    stages = {
        'generated': bool(answer.strip()),
        'syntax_ok': bool(code) and is_valid_python(code)[0],
        'has_repetition_loop': has_sentence_loop(answer) or has_consecutive_dup_lines(code),
    }

    exec_result = None
    if stages['syntax_ok'] and hint:
        if exec_policy == 'blocked':
            exec_result = {'status': 'BLOCKED', 'executed': False}
        else:
            runner = build_exec_runner(code, hint)
            if exec_policy == 'reviewed':
                exec_result = run_restricted(code, hint, timeout_sec=timeout_exec, reviewed=True)
            else:  # harness
                import subprocess, tempfile
                with tempfile.TemporaryDirectory(prefix='agf_harness_') as td:
                    script = Path(td) / 'runner.py'
                    script.write_text(runner, encoding='utf-8')
                    try:
                        proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                                              text=True, timeout=timeout_exec, cwd=td)
                        out, err, rc, to = proc.stdout, proc.stderr, proc.returncode, False
                    except subprocess.TimeoutExpired:
                        out, err, rc, to = '', f'timeout after {timeout_exec}s', -1, True
                status = ('PASSED' if rc == 0 and 'ALL_HINTS_PASS' in out
                          else 'TIMEOUT' if to else 'FAILED')
                exec_result = {'status': status, 'executed': True, 'returncode': rc,
                               'stdout': out[-2000:], 'stderr': err[-2000:], 'timed_out': to}

    passed = bool(exec_result and exec_result.get('executed')
                  and exec_result.get('status') == 'PASSED')
    failure = 'none'
    if exec_result is None:
        failure = 'no_code' if not stages['syntax_ok'] else 'no_hint'
    elif exec_result.get('status') == 'BLOCKED':
        failure = 'blocked'
    elif exec_result.get('status') == 'TIMEOUT':
        failure = 'timeout'
    elif exec_result.get('status') in ('FAILED', 'KILLED_BY_LIMIT'):
        stderr = exec_result.get('stderr', '')
        if 'SyntaxError' in stderr:
            failure = 'syntax_error'
        elif 'HINT_FAILURES:' in exec_result.get('stdout', ''):
            failure = 'wrong_result'
        elif 'blocked' in stderr:
            failure = 'policy_blocked'
        else:
            failure = 'runtime_error'

    return {
        'source_id': rec['source_id'],
        'task_type': rec.get('task_type', 'unknown'),
        'question': question,
        'test_hint': hint,
        'model_answer': answer,
        'final_code': code,
        'exec_status': exec_result.get('status') if exec_result else 'not_run',
        'exec_failure': failure,
        'failure_details': ((exec_result.get('stdout', '') + exec_result.get('stderr', ''))
                            if exec_result else '')[-600:],
        'passed': passed,
        'executed': bool(exec_result and exec_result.get('executed')),
        'stages': stages,
        'elapsed_sec': round(time.time() - t0, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', default='models/qwen3-0.6b-lora-v0')
    parser.add_argument('--model', default='Qwen/Qwen3-0.6B')
    parser.add_argument('--regression-set', default='data/eval/coding_regression_fixed.jsonl')
    parser.add_argument('--limit', type=int, default=0, help='0 = all tasks')
    parser.add_argument('--max-new-tokens', type=int, default=300)
    parser.add_argument('--timeout-gen', type=int, default=120)
    parser.add_argument('--timeout-exec', type=int, default=10)
    parser.add_argument('--exec-policy', default='reviewed', choices=('blocked', 'reviewed', 'harness'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    lines = [json.loads(l) for l in Path(args.regression_set).read_text(encoding='utf-8').splitlines()
             if l.strip()]
    tasks = lines[:args.limit] if args.limit else lines
    # UNIFIED prompt template for every run (consistency check anchors on this).
    prompt_template = '{question}'

    model, tokenizer = load_model_and_tokenizer(args.model, args.adapter)

    results = []
    t0 = time.time()
    for rec in tasks:
        r = exec_one_task(model, tokenizer, rec, args.max_new_tokens,
                          args.timeout_gen, args.timeout_exec,
                          args.exec_policy, prompt_template)
        results.append(r)
        print(json.dumps({'source_id': r['source_id'], 'passed': r['passed'],
                          'executed': r['executed'], 'failure': r['exec_failure']},
                         ensure_ascii=False), flush=True)

    passed = sum(1 for r in results if r['passed'])
    executed = sum(1 for r in results if r['executed'])
    test_hint_hash = __import__('hashlib').sha256(
        '\n'.join(rec.get('test_hint', '') for rec in tasks).encode('utf-8')).hexdigest()

    report = {
        'status': 'EXEC_REGRESSION_EVIDENCE',
        'adapter': args.adapter if args.adapter != 'none' else args.model,
        'base_model': args.model,
        'exec_policy': args.exec_policy,
        'prompt_template': prompt_template,
        'test_hint_hash': test_hint_hash,
        'regression_set': args.regression_set,
        'sampling': {'mode': 'greedy', 'max_new_tokens': args.max_new_tokens,
                     'timeout_gen': args.timeout_gen, 'timeout_exec': args.timeout_exec},
        'security': security_report(),
        'results': results,
        'summary': {
            'total': len(results),
            'passed': passed,
            'pass_rate': round(passed / len(results), 4) if results else 0.0,
            'executed': executed,
            'failure_breakdown': {k: sum(1 for r in results if r['exec_failure'] == k)
                                  for k in {r['exec_failure'] for r in results}},
        },
        'elapsed_sec': round(time.time() - t0, 1),
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
    print(json.dumps({'saved': args.output, 'summary': report['summary']},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
