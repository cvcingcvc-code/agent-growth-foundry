"""Offline unit tests for coding_pipeline.process_task (mock model, no GPU).

Covers the full pipeline: generate -> sandbox exec -> test -> failure
analysis -> one patch attempt -> retest, across five scenarios.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))

import coding_pipeline  # noqa: E402


class MockTokenizer:
    pass


class MockModel:
    pass


def fake_generate_factory(answers_by_call):
    call_n = {'n': 0}

    def generate_once(model, tokenizer, question, max_new_tokens, timeout_sec):
        idx = min(call_n['n'], len(answers_by_call) - 1)
        call_n['n'] += 1
        return {'text': answers_by_call[idx]}

    return generate_once


REC = {
    'source_id': 'mock-001', 'task_type': 'debug',
    'question': 'fix add(a, b) that returns a+b+1',
    'test_hint': 'add(1,2)==3',
}

WRONG = '```python\ndef add(a, b):\n    return a + b + 1\n```'
FIXED = '```python\ndef add(a, b):\n    return a + b\n```'
BAD_SYNTAX = '```python\ndef add(:\n    pass\n```'


class ProcessTaskTests(unittest.TestCase):

    def setUp(self):
        self.model, self.tok = MockModel(), MockTokenizer()

    def test_a_patch_fixes_failure(self):
        coding_pipeline.generate_once = fake_generate_factory([WRONG, FIXED])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10)
        self.assertTrue(r['passed'])
        self.assertTrue(r['patched'])
        self.assertEqual(r['failure'], 'none')

    def test_b_one_patch_attempt_only(self):
        coding_pipeline.generate_once = fake_generate_factory([WRONG, WRONG])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10)
        self.assertFalse(r['passed'])
        self.assertTrue(r['patched'])
        self.assertEqual(r['failure'], 'wrong_result')

    def test_c_syntax_error_skips_exec(self):
        coding_pipeline.generate_once = fake_generate_factory([BAD_SYNTAX, FIXED])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10)
        self.assertFalse(r['passed'])
        self.assertFalse(r['patched'])
        self.assertFalse(r['stages']['syntax_ok'])

    def test_d_correct_first_time_no_patch(self):
        coding_pipeline.generate_once = fake_generate_factory([FIXED])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10)
        self.assertTrue(r['passed'])
        self.assertFalse(r['patched'])

    def test_e_patch_disabled(self):
        coding_pipeline.generate_once = fake_generate_factory([WRONG, FIXED])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10,
                                         patch_attempt=False)
        self.assertFalse(r['passed'])
        self.assertFalse(r['patched'])
        self.assertEqual(r['failure'], 'wrong_result')

    def test_f_repetition_via_dup_code_lines(self):
        # Code form of sft-020: >=3 consecutive identical code lines.
        loop_code = '```python\ndef add(a, b):\n    return a\n    return a\n    return a\n```'
        coding_pipeline.generate_once = fake_generate_factory([loop_code])
        r = coding_pipeline.process_task(self.model, self.tok, REC, 300, 5, 10)
        self.assertTrue(r['stages']['has_repetition_loop'])


if __name__ == '__main__':
    unittest.main()
