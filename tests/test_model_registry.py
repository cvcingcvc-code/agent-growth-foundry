"""Unit tests for model_registry.py (pure functions, no GPU)."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.model_registry import (
    AdapterBaseMismatch, ModelNotInRegistry, check_binding, get_spec,
    resolve_adapter_base, upgrade_candidates,
)


class RegistryTests(unittest.TestCase):

    def test_get_spec_known(self):
        spec = get_spec('Qwen/Qwen3-0.6B')
        self.assertEqual(spec.family, 'qwen3')
        self.assertEqual(spec.params_b, 0.6)

    def test_get_spec_short_id(self):
        spec = get_spec('Qwen3-8B')
        self.assertEqual(spec.params_b, 8.0)

    def test_get_spec_unknown_raises(self):
        with self.assertRaises(ModelNotInRegistry):
            get_spec('Qwen/Qwen3-99B')


class BindingTests(unittest.TestCase):

    def test_known_binding_same_base_ok(self):
        check_binding('models/qwen3-0.6b-lora-v0', 'Qwen/Qwen3-0.6B')  # no raise

    def test_known_binding_other_base_raises(self):
        # 0.6B adapter on an 8B base: dimension-bound, must NOT attach.
        with self.assertRaises(AdapterBaseMismatch):
            check_binding('models/qwen3-0.6b-lora-v0', 'Qwen/Qwen3-8B')

    def test_coder_30b_rejects_06b_adapter(self):
        with self.assertRaises(AdapterBaseMismatch):
            check_binding('models/qwen3-0.6b-lora-v2',
                          'Qwen/Qwen3-Coder-30B-A3B-Instruct')

    def test_unknown_adapter_defers_to_champion_check(self):
        # Unknown adapters pass through here; champion.py checks their config.
        check_binding('models/some-unknown-adapter', 'Qwen/Qwen3-8B')  # no raise

    def test_resolve_returns_base(self):
        base = resolve_adapter_base('models/qwen3-0.6b-lora-v0', 'Qwen/Qwen3-0.6B')
        self.assertEqual(base, 'Qwen/Qwen3-0.6B')


class UpgradeTests(unittest.TestCase):

    def test_upgrade_candidates_shape(self):
        out = upgrade_candidates(6.0)  # GTX 1660 6GB
        ids = [c['model_id'] for c in out]
        self.assertIn('Qwen/Qwen3-0.6B', ids)
        self.assertIn('Qwen/Qwen3-8B', ids)
        for c in out:
            self.assertIn('fits_current_gpu_fp16', c)

    def test_6gb_card_fits_06b_not_8b_fp16(self):
        out = {c['model_id']: c for c in upgrade_candidates(6.0)}
        self.assertTrue(out['Qwen/Qwen3-0.6B']['fits_current_gpu_fp16'])
        self.assertFalse(out['Qwen/Qwen3-8B']['fits_current_gpu_fp16'])


if __name__ == '__main__':
    unittest.main()
