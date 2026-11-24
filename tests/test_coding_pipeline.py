"""Unit tests for coding_pipeline.py sandbox layer (offline, no GPU/model).

The sandbox executor runs real subprocesses with hard timeouts, so these
tests exercise the actual isolation boundary without loading any model.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))

from coding_pipeline import (  # noqa: E402
    analyze_failure, build_runner, run_in_sandbox, summarize_pipeline,
)


class BuildRunnerTests(unittest.TestCase):

    def test_code_and_hint_injected(self):
        src = build_runner('def f(x):\n    return x', "f(1)==1")
        self.assertIn('def f(x):', src)
        self.assertIn("f(1)==1", src)

    def test_placeholder_gone(self):
        src = build_runner('x = 1', 'x==1')
        self.assertNotIn('{code}', src)
        self.assertNotIn('[[HINT]]', src)


class SandboxTests(unittest.TestCase):

    def test_correct_code_passes(self):
        src = build_runner('def add(a, b):\n    return a + b', 'add(1,2)==3')
        r = run_in_sandbox(src, 10)
        self.assertEqual(r['returncode'], 0)
        self.assertIn('ALL_HINTS_PASS', r['stdout'])
        self.assertFalse(r['timed_out'])

    def test_wrong_result_detected(self):
        src = build_runner('def add(a, b):\n    return a + b + 1', 'add(1,2)==3')
        r = run_in_sandbox(src, 10)
        self.assertNotEqual(r['returncode'], 0)
        self.assertEqual(analyze_failure(r), 'wrong_result')

    def test_syntax_error_detected(self):
        src = build_runner('def f(:\n    pass', 'f(1)==1')
        r = run_in_sandbox(src, 10)
        self.assertNotEqual(r['returncode'], 0)
        self.assertEqual(analyze_failure(r), 'syntax_error')

    def test_timeout_kills_process(self):
        src = build_runner('def f(n):\n    while 1:\n        n += 1', 'f(1)==1')
        r = run_in_sandbox(src, 3)
        self.assertTrue(r['timed_out'])
        self.assertEqual(analyze_failure(r), 'timeout')

    def test_name_error_detected(self):
        src = build_runner('def f(x):\n    return unknown_var_xyz', 'f(1)==1')
        r = run_in_sandbox(src, 10)
        self.assertEqual(analyze_failure(r), 'name_error')

    def test_fresh_temp_dir_isolation(self):
        # Two consecutive runs must both succeed independently.
        src = build_runner('def g():\n    return 42', 'g()==42')
        for _ in range(2):
            r = run_in_sandbox(src, 10)
            self.assertEqual(r['returncode'], 0)


class SummarizeTests(unittest.TestCase):

    def test_summary_counts(self):
        results = [
            {'passed': True, 'patched': False, 'failure': 'none',
             'stages': {'has_repetition_loop': False, 'on_topic': True}},
            {'passed': True, 'patched': True, 'failure': 'wrong_result',
             'stages': {'has_repetition_loop': False, 'on_topic': True}},
            {'passed': False, 'patched': True, 'failure': 'timeout',
             'stages': {'has_repetition_loop': True, 'on_topic': False}},
        ]
        s = summarize_pipeline(results)
        self.assertEqual(s['total'], 3)
        self.assertEqual(s['passed'], 2)
        self.assertEqual(s['pass_rate'], round(2 / 3, 4))
        self.assertEqual(s['repetition_loops'], 1)
        self.assertEqual(s['off_topic'], 1)
        self.assertEqual(s['failure_breakdown'].get('timeout'), 1)

    def test_empty_results(self):
        s = summarize_pipeline([])
        self.assertEqual(s['total'], 0)
        self.assertEqual(s['pass_rate'], 0.0)


if __name__ == '__main__':
    unittest.main()
