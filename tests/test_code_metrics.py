"""Unit tests for code_metrics.py (pure functions, no GPU/model)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.code_metrics import (
    extract_code_blocks, has_repetition_loop, is_valid_python, patch_success_rate,
    reference_overlap, repetition_loop_rate, summarize, syntax_pass_rate,
    task_relevance_rate, unit_test_pass_rate,
)


class SyntaxTests(unittest.TestCase):
    def test_valid_code(self):
        ok, err = is_valid_python("def add(a, b):\n    return a + b\n")
        self.assertTrue(ok)
        self.assertEqual(err, '')

    def test_invalid_code(self):
        ok, err = is_valid_python("def add(a, b)\n    return a + b")  # missing colon
        self.assertFalse(ok)
        self.assertIn('line', err)

    def test_extract_fenced_block(self):
        text = "说明：\n```python\nprint(1)\n```\n结束"
        blocks = extract_code_blocks(text)
        self.assertEqual(len(blocks), 1)
        self.assertIn('print(1)', blocks[0])

    def test_extract_raw_fallback(self):
        self.assertEqual(extract_code_blocks("x = 1"), ["x = 1"])
        self.assertEqual(extract_code_blocks(""), [])

    def test_syntax_pass_rate(self):
        res = syntax_pass_rate(["```python\nprint(1)\n```", "def f(\n", "x = 1"])
        self.assertEqual(res['total'], 3)
        self.assertEqual(res['passed'], 2)
        self.assertEqual(res['rate'], 0.6667)
        self.assertEqual(len(res['errors']), 1)

    def test_empty_rate_is_zero(self):
        self.assertEqual(syntax_pass_rate([])['rate'], 0.0)
        self.assertEqual(repetition_loop_rate([])['rate'], 0.0)


class RepetitionTests(unittest.TestCase):
    def test_loop_detected(self):
        text = "需手动重置并重新启动；若程序已断电，需手动重置并重新启动；若程序已断电，需手动重置并重新启动。"
        self.assertTrue(has_repetition_loop(text))

    def test_normal_not_flagged(self):
        self.assertFalse(has_repetition_loop("把任务状态持久化，重启时从最后完成的步骤继续。"))

    def test_rate(self):
        res = repetition_loop_rate(["ok normal answer here", "需手动重置；需手动重置；需手动重置并重新启动程序循环。"])
        self.assertEqual(res['total'], 2)
        self.assertEqual(res['flagged'], 1)


class RelevanceTests(unittest.TestCase):
    def test_on_topic(self):
        ov = reference_overlap("用独立测试问题比较基础模型和微调版本。", "独立测试问题比较基础模型与微调版本并分析失败。")
        self.assertGreater(ov, 0.5)

    def test_off_topic(self):
        ov = reference_overlap("今天天气很好适合散步。", "判断模型是否死记硬背训练样本的方法。")
        self.assertLess(ov, 0.15)

    def test_rate(self):
        res = task_relevance_rate(["用独立测试问题比较模型。", "今天天气很好适合散步。"],
                                  ["独立测试问题比较模型版本。", "判断死记硬背的方法。"])
        self.assertEqual(res['total'], 2)
        self.assertEqual(res['on_topic'], 1)
        self.assertEqual(res['rate'], 0.5)


class ExecutionTests(unittest.TestCase):
    def test_unit_test_pass_rate(self):
        self.assertEqual(unit_test_pass_rate([True, True, False]), {'total': 3, 'passed': 2, 'rate': 0.6667})
        self.assertEqual(unit_test_pass_rate([])['rate'], 0.0)

    def test_patch_success_rate(self):
        attempts = [
            {'task': 'add', 'buggy_passed': False, 'patched_passed': True},
            {'task': 'mul', 'buggy_passed': False, 'patched_passed': False},
            {'task': 'sub', 'buggy_passed': True, 'patched_passed': True},  # not eligible
        ]
        self.assertEqual(patch_success_rate(attempts), {'total': 2, 'patched': 1, 'rate': 0.5})
        self.assertEqual(patch_success_rate([])['rate'], 0.0)


class SummarizeTests(unittest.TestCase):
    def test_combined(self):
        s = summarize(["```python\nprint(1)\n```", "def f(\n"], ["输出数字", "输出数字"],
                      test_results=[True, False],
                      patch_attempts=[{'buggy_passed': False, 'patched_passed': True}])
        self.assertEqual(s['syntax']['passed'], 1)
        self.assertEqual(s['unit_test']['passed'], 1)
        self.assertEqual(s['patch']['patched'], 1)
        self.assertEqual(s['relevance']['total'], 2)

    def test_without_optional(self):
        s = summarize(["x = 1"], ["输出"])
        self.assertIsNone(s['unit_test'])
        self.assertIsNone(s['patch'])


if __name__ == '__main__':
    unittest.main()
