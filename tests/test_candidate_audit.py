"""Unit tests for candidate_audit.py (pure functions, no GPU/model)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.candidate_audit import (
    audit_candidates, check_record, defines_function, has_consecutive_dup_lines,
    has_sentence_loop, scan_eval_leakage, split_prose_and_code,
)


def _rec(sid, ttype, q, a, **extra):
    item = {
        'source_id': sid, 'rights': 'self_authored', 'reviewed_by': 'x',
        'split': 'train', 'task_type': ttype,
        'messages': [{'role': 'user', 'content': q}, {'role': 'assistant', 'content': a}],
        'note': 'n',
    }
    item.update(extra)
    return item


class SplitTests(unittest.TestCase):

    def test_fenced_code_extracted(self):
        prose, blocks = split_prose_and_code('说明\n```python\nx = 1\n```')
        self.assertEqual(prose, '说明')
        self.assertEqual(len(blocks), 1)

    def test_no_code_falls_back(self):
        prose, blocks = split_prose_and_code('只有解释')
        self.assertEqual(prose, '只有解释')
        # extract_code_blocks falls back to the raw text as one block.
        self.assertEqual(blocks, ['只有解释'])


class DupLineTests(unittest.TestCase):

    def test_consecutive_triggers(self):
        self.assertTrue(has_consecutive_dup_lines('a\na\na'))

    def test_non_consecutive_ok(self):
        self.assertFalse(has_consecutive_dup_lines('a\nb\na'))

    def test_threshold_respected(self):
        self.assertFalse(has_consecutive_dup_lines('a\na'))


class SentenceLoopTests(unittest.TestCase):

    def test_sentence_loop_triggers(self):
        self.assertTrue(has_sentence_loop('这是第一句话内容很长\n这是第一句话内容很长'))

    def test_topical_reuse_ok(self):
        self.assertFalse(has_sentence_loop('评测集保证分数可以直接比较；评测集差异不是模型差异。'))


class DefineTests(unittest.TestCase):

    def test_defines_function_true(self):
        self.assertTrue(defines_function('def foo(x):\n    return x', 'foo'))

    def test_defines_function_false(self):
        self.assertFalse(defines_function('def bar(x):\n    return x', 'foo'))


class RecordRuleTests(unittest.TestCase):

    def test_code_gen_ok(self):
        item = _rec('a', 'code_gen', '写函数 foo', '```python\ndef foo(x):\n    return x\n```',
                    target_func='foo')
        self.assertEqual(check_record(item), [])

    def test_code_gen_syntax_error(self):
        item = _rec('a', 'code_gen', '写函数 foo', '```python\ndef foo(:\n    pass\n```',
                    target_func='foo')
        reasons = check_record(item)
        self.assertTrue(any('syntax error' in r for r in reasons))

    def test_code_gen_target_not_defined(self):
        item = _rec('a', 'code_gen', '写函数 foo', '```python\ndef other():\n    pass\n```',
                    target_func='foo')
        reasons = check_record(item)
        self.assertTrue(any('not defined' in r for r in reasons))

    def test_code_gen_dup_lines_rejected(self):
        item = _rec('a', 'code_gen', '写函数 foo',
                    '```python\ndef foo():\n    return 1\n    return 1\n    return 1\n```',
                    target_func='foo')
        reasons = check_record(item)
        self.assertTrue(any('consecutive identical' in r for r in reasons))

    def test_qa_key_term_missing(self):
        item = _rec('a', 'qa', '问题是什么', '这个回答内容足够长但没有那个关键词', key_terms=['不存在的词'])
        reasons = check_record(item)
        self.assertTrue(any('key term missing' in r for r in reasons))

    def test_019_answer_not_python(self):
        # A Chinese sentence with punctuation is NOT valid python
        # (unlike a bare identifier expression, which parses).
        item = _rec('a', 'counterexample_019', '直接用代码回答', '这不是代码，这是一段解释文字而已啊。')
        reasons = check_record(item)
        self.assertTrue(any('not valid python' in r for r in reasons))

    def test_020_two_sentences(self):
        item = _rec('a', 'counterexample_020', '一句话说明', '第一句话在这里。第二句话也在这里。')
        reasons = check_record(item)
        self.assertTrue(any('sentence' in r for r in reasons))


class AuditTests(unittest.TestCase):

    def test_duplicate_source_id_rejected(self):
        # First-wins policy: the first occurrence stays approved, the
        # duplicate is rejected and both collide on the same pair.
        rec = _rec('dup', 'qa', '问题是什么', '这个回答内容足够长', key_terms=[])
        dup = dict(rec)
        dup['reviewed_by'] = 'other'
        rep = audit_candidates([rec, dup])
        self.assertEqual(rep['approved_count'], 1)
        self.assertEqual(rep['rejected_count'], 1)
        self.assertTrue(all('duplicate' in ' '.join(r['reasons'])
                            for r in rep['rejected']))

    def test_rights_must_be_self_authored(self):
        rec = _rec('a', 'qa', '问题', '回答内容足够长了', key_terms=[])
        rec['rights'] = 'scraped'
        rep = audit_candidates([rec])
        self.assertEqual(rep['approved_count'], 0)

    def test_split_must_be_train(self):
        rec = _rec('a', 'qa', '问题', '回答内容足够长了', key_terms=[])
        rec['split'] = 'eval'
        rep = audit_candidates([rec])
        self.assertEqual(rep['approved_count'], 0)


class LeakageTests(unittest.TestCase):

    def test_builtin_names_not_flagged(self):
        rep = scan_eval_leakage(
            [_rec('a', 'code_gen', '用 len 和 sum 处理', 'x', target_func='f')],
            ['用 len 计算总和'])
        self.assertEqual(rep, [])

    def test_method_calls_not_flagged(self):
        rep = scan_eval_leakage(
            [_rec('a', 'code_gen', '用 target.append 添加', 'x', target_func='f')],
            ['def append_to(item, target=[]): target.append(item)'])
        self.assertEqual(rep, [])

    def test_real_overlap_flagged(self):
        rep = scan_eval_leakage(
            [_rec('a', 'code_gen', '写一个 foo_bar(x) 函数', 'x', target_func='foo_bar')],
            ['写一个 foo_bar(x) 函数'])
        self.assertEqual(len(rep), 1)
        self.assertEqual(rep[0]['overlapping_names'], ['foo_bar'])


if __name__ == '__main__':
    unittest.main()
