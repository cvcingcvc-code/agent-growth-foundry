"""Unit tests for champion.py registry (no GPU/weights needed)."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.champion import (
    Champion, adapter_base_compatible, append_history, base_family,
    build_promotion_suggestion, champion_comparison_ready, load_champion, save_champion,
)


class RegistryIOTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'champion.json'
            c = Champion('models/v0', 'Qwen/Qwen3-0.6B', '2026-10-21T00:00:00+00:00',
                         'human_operator', 5.197, ['ev1.json'])
            save_champion(path, c)
            loaded = load_champion(path)
            self.assertEqual(loaded.adapter, 'models/v0')
            self.assertEqual(loaded.eval_loss, 5.197)
            self.assertEqual(loaded.approved_by, 'human_operator')

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_champion(Path('Z:/definitely/missing/champion.json')))

    def test_corrupt_file_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'champion.json'
            path.write_text(json.dumps({'adapter': 'x'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_champion(path)

    def test_history_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'history.jsonl'
            append_history(path, {'run': 1, 'decision': 'HOLD'})
            append_history(path, {'run': 2, 'decision': 'PROMOTE'})
            lines = path.read_text(encoding='utf-8').strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])['run'], 1)
            self.assertEqual(json.loads(lines[1])['run'], 2)


class CompatibilityTests(unittest.TestCase):
    def test_same_family_compatible(self):
        self.assertTrue(adapter_base_compatible({'base_model': 'Qwen/Qwen3-0.6B'}, 'Qwen/Qwen3-0.6B'))

    def test_cross_size_incompatible(self):
        # 0.6B adapter must NOT be mounted onto a 3B/8B base
        self.assertFalse(adapter_base_compatible({'base_model': 'Qwen/Qwen3-0.6B'}, 'Qwen/Qwen3-4B'))
        self.assertFalse(adapter_base_compatible({'base_model': 'Qwen/Qwen3-0.6B'}, 'Qwen/Qwen3-8B'))

    def test_unknown_provenance_incompatible(self):
        self.assertFalse(adapter_base_compatible({}, 'Qwen/Qwen3-0.6B'))

    def test_base_family_extraction(self):
        self.assertEqual(base_family('Qwen/Qwen3-0.6B'), 'Qwen/Qwen3')
        self.assertEqual(base_family('Qwen/Qwen3-Coder-30B'), 'Qwen/Qwen3-Coder')


class ComparisonGateTests(unittest.TestCase):
    def test_no_champion_holds(self):
        ok, reason = champion_comparison_ready(None, None)
        self.assertFalse(ok)
        self.assertIn('no champion', reason)

    def test_missing_evidence_holds(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        ok, reason = champion_comparison_ready(c, 'Z:/missing/eval.json')
        self.assertFalse(ok)
        self.assertIn('HOLD', reason)

    def test_ready_with_evidence(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text(json.dumps({'status': 'BASE_VS_LORA_COMPARISON_ONLY_NOT_SIGNIFICANCE_CLAIM',
                                      'samples': 2,
                                      'items': [{'source_id': 's1'}, {'source_id': 's2'}]}),
                          encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev)
            self.assertTrue(ok, reason)

    def test_empty_json_evidence_holds(self):
        # Round-4.1 anti-bypass: an empty '{}' evidence file must NOT pass.
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text('{}', encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev)
            self.assertFalse(ok)
            self.assertIn('HOLD', reason)

    def test_no_items_evidence_holds(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text(json.dumps({'status': 'something', 'samples': 4}), encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev)
            self.assertFalse(ok)
            self.assertIn('no per-sample items', reason)

    def test_too_few_samples_holds(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text(json.dumps({'items': [{'source_id': 's1'}]}), encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev, expected_samples=4)
            self.assertFalse(ok)
            self.assertIn('need >= 4', reason)

    def test_dataset_fingerprint_mismatch_holds(self):
        # Round-4.1 anti-bypass: evidence recorded for a DIFFERENT dataset
        # must not let a candidate bypass the regression gate.
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text(json.dumps({'items': [{'source_id': 's1'}, {'source_id': 's2'}],
                                      'dataset_fingerprint': {'sha256': 'a' * 64, 'count': 2}}),
                          encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev, expected_dataset_sha256='b' * 64)
            self.assertFalse(ok)
            self.assertIn('fingerprint mismatch', reason)

    def test_dataset_fingerprint_match_passes(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text(json.dumps({'items': [{'source_id': 's1'}, {'source_id': 's2'}],
                                      'dataset_fingerprint': {'sha256': 'b' * 64, 'count': 2}}),
                          encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev, expected_dataset_sha256='b' * 64)
            self.assertTrue(ok, reason)

    def test_unreadable_evidence_holds(self):
        c = Champion('models/v0', 'Qwen/Qwen3-0.6B', 't', 'human', 5.0, [])
        with tempfile.TemporaryDirectory() as td:
            ev = Path(td) / 'eval.json'
            ev.write_text('not json at all', encoding='utf-8')
            ok, reason = champion_comparison_ready(c, ev)
            self.assertFalse(ok)
            self.assertIn('unreadable', reason)


class SuggestionTests(unittest.TestCase):
    def test_promote_is_pending_not_applied(self):
        s = build_promotion_suggestion('PROMOTE', ['loss improved'], 'models/v3', 'models/v0')
        self.assertTrue(s['pending_human_review'])
        self.assertFalse(s['champion_changed'])

    def test_hold_not_pending(self):
        s = build_promotion_suggestion('HOLD', ['regression'], 'models/v3', 'models/v0')
        self.assertFalse(s['pending_human_review'])
        self.assertFalse(s['champion_changed'])


if __name__ == '__main__':
    unittest.main()
