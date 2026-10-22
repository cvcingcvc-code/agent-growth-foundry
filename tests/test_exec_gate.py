"""Unit tests for exec_gate.py (pure decision logic, no GPU/model).

Covers all four judgment rules: evidence missing -> HOLD, inconsistent
conditions -> HOLD, new regression -> HOLD, non-degeneration -> PROMOTE
suggestion only.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.exec_gate import (
    conditions_consistent, decide_promotion_exec_level, dataset_fingerprint, sha256_text,
)


def _run(results: list[tuple[str, bool]], base='Qwen/Qwen3-0.6B', mode='greedy',
         mnt=300, template='{question}', hint_hash='H1'):
    return {
        'base_model': base, 'sampling_mode': mode, 'max_new_tokens': mnt,
        'prompt_template': template, 'test_hint_hash': hint_hash,
        'results': [{'source_id': sid, 'passed': p, 'executed': True,
                     'failure': 'none' if p else 'wrong_result'} for sid, p in results],
    }


class EvidenceMissingTests(unittest.TestCase):

    def test_candidate_not_executed_holds(self):
        cand = {'base_model': 'B', 'sampling_mode': 'greedy', 'max_new_tokens': 300,
                'prompt_template': '{q}', 'test_hint_hash': 'H',
                'results': [{'source_id': 't1', 'passed': False, 'executed': False}]}
        champ = _run([('t1', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('missing', d['reasons'][0])

    def test_no_results_holds(self):
        cand = {'base_model': 'B', 'results': []}
        champ = _run([('t1', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')

    def test_champion_evidence_missing_holds(self):
        cand = _run([('t1', True)])
        champ = {'base_model': 'B', 'results': []}
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('champion', d['reasons'][0])


class ConsistencyTests(unittest.TestCase):

    def test_conditions_consistent_true(self):
        ok, problems = conditions_consistent(_run([('t1', True)]), _run([('t1', False)]))
        self.assertTrue(ok)
        self.assertEqual(problems, [])

    def test_different_base_holds(self):
        cand = _run([('t1', True)], base='Qwen/Qwen3-8B')
        champ = _run([('t1', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('base model', d['reasons'][0])

    def test_different_tests_holds(self):
        cand = _run([('t1', True)], hint_hash='H2')
        champ = _run([('t1', True)], hint_hash='H1')
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('test-hint', d['reasons'][0])

    def test_different_sampling_holds(self):
        cand = _run([('t1', True)], mnt=200)
        champ = _run([('t1', True)], mnt=300)
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('max_new_tokens', d['reasons'][0])

    def test_different_template_holds(self):
        cand = _run([('t1', True)], template='Q: {question}')
        champ = _run([('t1', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')


class RegressionTests(unittest.TestCase):

    def test_new_regression_holds(self):
        # Champion passed t2, candidate fails t2 -> HOLD even if candidate
        # passes more tasks overall.
        cand = _run([('t1', True), ('t2', False), ('t3', True)])
        champ = _run([('t1', True), ('t2', True), ('t3', False)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('t2', d['reasons'][0])

    def test_both_fail_same_task_not_regression(self):
        # Same failures on both sides: not a NEW regression, but 1/2 pass rate
        # is below the 0.6 bar -> HOLD (correct conservative behavior).
        cand = _run([('t1', False), ('t2', True)])
        champ = _run([('t1', False), ('t2', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('below bar', d['reasons'][0])


class PromotionTests(unittest.TestCase):

    def test_meets_bar_promote_suggestion_only(self):
        cand = _run([('t%d' % i, True) for i in range(1, 8)] + [('t8', False), ('t9', False), ('t10', False)])
        champ = _run([('t%d' % i, True) for i in range(1, 8)] + [('t8', False), ('t9', False), ('t10', False)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'PROMOTE')
        self.assertTrue(d['pending_human_review'])
        self.assertFalse(d.get('champion_changed', True))

    def test_below_bar_holds(self):
        cand = _run([('t1', True), ('t2', False), ('t3', False), ('t4', False)])
        champ = _run([('t1', False), ('t2', False), ('t3', False), ('t4', False)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')

    def test_round4_evidence_v3b_rejected(self):
        # The real round-4 finding: v3b fails t1/t9 where v0 passed -> HOLD.
        cand = _run([('t1', False), ('t6', False), ('t9', False), ('t10', True)])
        champ = _run([('t1', True), ('t6', False), ('t9', True), ('t10', True)])
        d = decide_promotion_exec_level(cand, champ)
        self.assertEqual(d['decision'], 'HOLD')
        self.assertIn('t1', d['reasons'][0])


class FingerprintTests(unittest.TestCase):

    def test_sha256_text_stable(self):
        self.assertEqual(sha256_text('abc'), sha256_text('abc'))
        self.assertNotEqual(sha256_text('abc'), sha256_text('abd'))

    def test_dataset_fingerprint_missing(self):
        fp = dataset_fingerprint('Z:/nonexistent/file.jsonl')
        self.assertFalse(fp['exists'])

    def test_dataset_fingerprint_real(self):
        p = Path(__file__).resolve().parents[1] / 'data' / 'eval' / 'coding_regression_fixed.jsonl'
        if not p.exists():
            self.skipTest('regression set not present')
        fp = dataset_fingerprint(p)
        self.assertTrue(fp['exists'])
        self.assertEqual(fp['count'], 10)


if __name__ == '__main__':
    unittest.main()
