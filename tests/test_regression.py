"""Unit tests for regression.py gate (round-2 failure modes + promotion logic)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.regression import (
    check_repetition, check_sample, decide_promotion, reference_overlap,
    SampleCheck,
)


class RepetitionTests(unittest.TestCase):
    def test_repetition_loop_detected(self):
        # round-2 sft-020 failure mode: phrase repeats 3+ times
        text = "断电后恢复任务，需先断电，再重新启动程序；若程序已断电，需手动重置并重新启动；若程序已断电，需手动重置并重新启动；若程序已断电，需手动重置并重新启动。"
        self.assertTrue(check_repetition(text))

    def test_normal_answer_not_flagged(self):
        text = "将任务状态、输入、产物和事件持久化，重启时从最后完成的可靠步骤继续执行，避免重复已成功的工作。"
        self.assertFalse(check_repetition(text))

    def test_short_answer_not_flagged(self):
        self.assertFalse(check_repetition("不能。"))


class OverlapTests(unittest.TestCase):
    def test_off_topic_low_overlap(self):
        answer = "今天天气很好，适合出门散步和运动放松心情。"
        reference = "使用训练期间未出现的独立测试问题，比较基础模型和微调版本并分析失败类型。"
        self.assertLess(reference_overlap(answer, reference), 0.15)

    def test_on_topic_high_overlap(self):
        answer = "使用独立测试问题比较基础模型和微调版本，分析失败类型。"
        reference = "使用训练期间未出现的独立测试问题，比较基础模型和微调版本并分析失败类型。"
        self.assertGreater(reference_overlap(answer, reference), 0.5)

    def test_check_sample_flags_degeneration(self):
        off = check_sample("sft-019", "今天天气很好适合出门散步放松。", "独立测试问题比较基础模型和微调版本。")
        self.assertTrue(off.degenerated)
        ok = check_sample("sft-018", "自动生产的资料可能包含错误，需要人工审核确保准确性和质量。",
                          "事实、授权、功能与用户价值不能只靠模型自评；人工审核避免错误交付。")
        self.assertFalse(ok.degenerated)


class PromotionTests(unittest.TestCase):
    @staticmethod
    def _checks(deg_ids):
        # deg_ids may hold full ids ("sft-019") or suffixes ("019")
        def deg(n):
            return f"sft-{n:03d}" in deg_ids or f"{n:03d}" in deg_ids
        return [SampleCheck(f"sft-{n:03d}", deg(n), 0.5 if not deg(n) else 0.10,
                            deg(n), "ok" if not deg(n) else "low-reference-overlap(0.10)")
                for n in range(17, 21)]

    def test_promote_when_loss_improves_and_no_regression(self):
        d = decide_promotion({"eval_loss": 4.0}, {"eval_loss": 5.197},
                             self._checks(set()), self._checks({"019", "020"}))
        self.assertEqual(d.decision, "PROMOTE")

    def test_hold_when_new_regressions_appear(self):
        # round-2 real case: old degenerated 019/020, new version degenerates 019/020 again is ok,
        # but a NEW regression (e.g. 018 breaks) must HOLD
        d = decide_promotion({"eval_loss": 4.356}, {"eval_loss": 5.197},
                             self._checks({"018", "019", "020"}), self._checks({"019", "020"}))
        self.assertEqual(d.decision, "HOLD")
        self.assertIn("new regressions: sft-018", ";".join(d.reasons))

    def test_hold_when_loss_not_improved(self):
        d = decide_promotion({"eval_loss": 5.3}, {"eval_loss": 5.197},
                             self._checks(set()), self._checks(set()))
        self.assertEqual(d.decision, "HOLD")

    def test_hold_when_degenerated_increased(self):
        d = decide_promotion({"eval_loss": 4.0}, {"eval_loss": 5.197},
                             self._checks({"017", "018", "019", "020"}), self._checks({"019"}))
        self.assertEqual(d.decision, "HOLD")

    def test_hold_on_missing_metrics(self):
        d = decide_promotion({}, {"eval_loss": 5.197}, self._checks(set()), self._checks(set()))
        self.assertEqual(d.decision, "HOLD")


if __name__ == '__main__':
    unittest.main()
