"""Coding-task sandbox pipeline: generate -> isolated execution -> test ->
failure analysis -> one patch attempt -> audit -> candidate pool.

Safety rules (AGENTS.md):
- Generated code runs in a SUBPROCESS with a hard timeout; on timeout the
  process is killed. Code never runs inside this process.
- Each run gets a fresh temp directory; the subprocess cwd is that temp dir.
- No network, no installs: the harness never executes pip/npm and generated
  code that tries to open network sockets still runs, but the harness itself
  performs no network calls.
- One patch attempt per task maximum (AGENTS.md rule 6: max 3 auto-fixes,
  this pipeline uses 1 by default).

Test oracle: the task's test_hint string like "f('x')==1; f('y')==2"
is translated into assert statements executed after importing the code.

Usage:
  python scripts/coding_pipeline.py --adapter models/qwen3-0.6b-lora-v0 \
      --tasks data/eval/coding_eval_v1.jsonl --limit 5 \
      --out outputs/coding_pipeline_v0.json
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
from chat_local import generate_once, load_model_and_tokenizer  # noqa: E402
from growthfoundry.code_metrics import (  # noqa: E402
    extract_code_blocks, is_valid_python, reference_overlap,
)
from growthfoundry.candidate_audit import (  # noqa: E402
    has_consecutive_dup_lines, has_sentence_loop,
)

RUNNER_TEMPLATE = '''# sandbox test runner
import sys
import re

def _hint_to_asserts(hint, namespace):
    """Translate 'f(1)==2; g(3)==4' hints into asserts against namespace."""
    results = []
    for part in hint.split(';'):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.*?)(==|!=|>=|<=|>|<)(.*)$", part)
        if not m:
            raise ValueError(f"bad hint fragment: [[part]]")
        expr, op, expected = m.group(1).strip(), m.group(2), m.group(3).strip()
        actual = eval(expr, dict(namespace))  # noqa: S307 - sandboxed harness
        results.append((part, op, expected, actual))
    return results


{code}
_ns = dict([_n for _n in globals().items() if not _n[0].startswith('_')])
failures = []
for part, op, expected_raw, actual in _hint_to_asserts([[HINT]], _ns):
    expected = eval(expected_raw, dict(_ns))
    ops = {
        '==': lambda a, b: a == b, '!=': lambda a, b: a != b,
        '>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b,
        '>': lambda a, b: a > b, '<': lambda a, b: a < b,
    }
    ok = ops[op](actual, expected)
    if not ok:
        failures.append(part + ": expected " + repr(expected) + ", got " + repr(actual))
if failures:
    print("HINT_FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("ALL_HINTS_PASS")
'''


def build_runner(code: str, hint: str) -> str:
    return RUNNER_TEMPLATE.replace('{code}', code).replace('[[HINT]]', repr(hint)) \
        .replace('[[part]]', 'part')


def run_in_sandbox(runner_src: str, timeout_sec: int) -> dict:
    """Execute the runner in a subprocess (fresh temp dir, hard timeout)."""
    with tempfile.TemporaryDirectory(prefix='agf_sandbox_') as td:
        script = Path(td) / 'runner.py'
        script.write_text(runner_src, encoding='utf-8')
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=timeout_sec, cwd=td,
            )
            return {'returncode': proc.returncode, 'stdout': proc.stdout[-2000:],
                    'stderr': proc.stderr[-2000:], 'timed_out': False}
        except subprocess.TimeoutExpired:
            return {'returncode': -1, 'stdout': '', 'stderr': f'timeout after {timeout_sec}s',
                    'timed_out': True}


def analyze_failure(exec_result: dict) -> str:
    """Classify a failure into a repair hint category."""
    if exec_result.get('timed_out'):
        return 'timeout'
    stderr = exec_result.get('stderr', '')
    stdout = exec_result.get('stdout', '')
    if 'SyntaxError' in stderr:
        return 'syntax_error'
    if 'NameError' in stderr:
        return 'name_error'
    if 'TypeError' in stderr:
        return 'type_error'
    if 'IndexError' in stderr or 'KeyError' in stderr:
        return 'index_or_key_error'
    if 'HINT_FAILURES:' in stdout:
        return 'wrong_result'
    if exec_result.get('returncode', 0) != 0:
        return 'runtime_error'
    return 'none'


PATCH_PROMPT = """你之前的代码没有通过测试。

任务：{question}

你之前的代码：
```python
{prev_code}
```

失败原因：{failure}
失败详情：
{details}

请修复代码，只输出修复后的完整代码，不要解释。"""


def hint_for_task(rec: dict) -> str:
    return rec.get('test_hint', '')


def task_relevant(question: str, answer: str) -> bool:
    return reference_overlap(answer, question) >= 0.15


def process_task(model, tokenizer, rec: dict, max_new_tokens: int,
                 timeout_gen: int, timeout_exec: int, patch_attempt: bool = True) -> dict:
    """One task through the full pipeline; returns a record of every stage."""
    question = rec['question']
    hint = hint_for_task(rec)
    t0 = time.time()

    res = generate_once(model, tokenizer, question, max_new_tokens, timeout_gen)
    answer = res.get('text', '')
    blocks = extract_code_blocks(answer)
    code = '\n\n'.join(blocks)

    stages = {
        'generated': bool(answer.strip()),
        'syntax_ok': bool(code) and is_valid_python(code)[0],
        # Repetition signal: sentence-level prose loop (sft-020 failure
        # mode) or >=3 consecutive identical code lines (the code form).
        # The 2-gram word check is NOT used here because normal code
        # legitimately reuses variable names.
        'has_repetition_loop': has_sentence_loop(answer) or has_consecutive_dup_lines(code),
        'on_topic': task_relevant(question, answer),
    }

    exec_result, failure, failure_details, patched = None, 'none', '', False
    if stages['syntax_ok'] and hint:
        runner = build_runner(code, hint)
        exec_result = run_in_sandbox(runner, timeout_exec)
        failure = analyze_failure(exec_result)
        failure_details = (exec_result.get('stdout', '') + exec_result.get('stderr', ''))[-600:]

        if failure != 'none' and patch_attempt:
            patch_res = generate_once(
                model, tokenizer,
                PATCH_PROMPT.format(question=question, prev_code=code,
                                    failure=failure, details=failure_details or '(no details)'),
                max_new_tokens, timeout_gen)
            patch_answer = patch_res.get('text', '')
            patch_blocks = extract_code_blocks(patch_answer)
            patch_code = '\n\n'.join(patch_blocks)
            stages['syntax_ok'] = bool(patch_code) and is_valid_python(patch_code)[0]
            if stages['syntax_ok']:
                patched = True
                code = patch_code
                answer = patch_answer
                exec_result = run_in_sandbox(build_runner(code, hint), timeout_exec)
                failure = analyze_failure(exec_result)
                failure_details = (exec_result.get('stdout', '') + exec_result.get('stderr', ''))[-600:]

    passed = bool(exec_result and exec_result.get('returncode') == 0
                  and 'ALL_HINTS_PASS' in exec_result.get('stdout', ''))
    stages['hint_test_passed'] = passed

    return {
        'source_id': rec['source_id'],
        'task_type': rec.get('task_type', 'unknown'),
        'question': question,
        'test_hint': hint,
        'model_answer': answer,
        'final_code': code,
        'patched': patched,
        'failure': failure,
        'failure_details': failure_details,
        'stages': stages,
        'passed': passed,
        'elapsed_sec': round(time.time() - t0, 1),
    }


def summarize_pipeline(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r['passed'])
    patched_runs = [r for r in results if r.get('patched')]
    return {
        'total': n,
        'passed': passed,
        'pass_rate': round(passed / n, 4) if n else 0.0,
        'patch_attempted': len(patched_runs),
        'patch_success_rate': round(len([r for r in patched_runs if r['passed']])
                                    / len(patched_runs), 4) if patched_runs else 0.0,
        'failure_breakdown': {
            k: sum(1 for r in results if r.get('failure') == k)
            for k in {r.get('failure', 'none') for r in results}
        },
        'repetition_loops': sum(1 for r in results if r['stages'].get('has_repetition_loop')),
        'off_topic': sum(1 for r in results if not r['stages'].get('on_topic')),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapter', default='models/qwen3-0.6b-lora-v0')
    parser.add_argument('--model', default='Qwen/Qwen3-0.6B')
    parser.add_argument('--tasks', default='data/eval/coding_eval_v1.jsonl')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--max-new-tokens', type=int, default=300)
    parser.add_argument('--timeout-gen', type=int, default=120)
    parser.add_argument('--timeout-exec', type=int, default=10)
    parser.add_argument('--no-patch', action='store_true', help='disable the one patch attempt')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()

    lines = [json.loads(l) for l in Path(args.tasks).read_text(encoding='utf-8').splitlines()
             if l.strip()]
    tasks = lines[:args.limit]

    model, tokenizer = load_model_and_tokenizer(args.model, args.adapter)
    label = args.adapter if args.adapter != 'none' else args.model

    results = []
    for rec in tasks:
        r = process_task(model, tokenizer, rec, args.max_new_tokens,
                         args.timeout_gen, args.timeout_exec, patch_attempt=not args.no_patch)
        results.append(r)
        print(json.dumps({'source_id': r['source_id'], 'passed': r['passed'],
                          'patched': r['patched'], 'failure': r['failure']},
                         ensure_ascii=False), flush=True)

    report = {
        'status': 'CODING_PIPELINE_EVIDENCE',
        'adapter': label,
        'sampling': {'mode': 'greedy', 'max_new_tokens': args.max_new_tokens,
                     'timeout_gen': args.timeout_gen, 'timeout_exec': args.timeout_exec,
                     'patch_attempt_enabled': not args.no_patch},
        'results': results,
        'summary': summarize_pipeline(results),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding='utf-8')
    print(json.dumps({'saved': args.out, 'summary': report['summary']},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
