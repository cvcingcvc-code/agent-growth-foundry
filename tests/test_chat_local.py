"""Unit tests for chat_local.py pure logic (no GPU/weights needed)."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chat_local import (
    adapter_base_matches, adapter_version_info, build_arg_parser, print_turn,
)


class VersionInfoTests(unittest.TestCase):
    def test_base_mode_info(self):
        info = adapter_version_info('none', 'Qwen/Qwen3-0.6B')
        self.assertEqual(info['mode'], 'base')
        self.assertEqual(info['base_model'], 'Qwen/Qwen3-0.6B')
        self.assertNotIn('lora', info)

    def test_adapter_info_reads_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / 'adapter_config.json'
            cfg.write_text(json.dumps({'r': 8, 'lora_alpha': 16, 'target_modules': ['q_proj']}), encoding='utf-8')
            (Path(td) / 'adapter_model.safetensors').write_bytes(b'x' * 10)
            info = adapter_version_info(td, 'Qwen/Qwen3-0.6B')
            self.assertEqual(info['mode'], 'lora')
            self.assertEqual(info['lora']['r'], 8)
            self.assertEqual(info['adapter_weights_bytes'], 10)

    def test_missing_adapter_config_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                adapter_version_info(td, 'Qwen/Qwen3-0.6B')


class ArgParserTests(unittest.TestCase):
    def test_defaults(self):
        a = build_arg_parser().parse_args([])
        self.assertEqual(a.adapter, 'models/qwen3-0.6b-lora-v0')
        self.assertEqual(a.max_new_tokens, 256)
        self.assertIsNone(a.question)

    def test_adapter_none_switch(self):
        a = build_arg_parser().parse_args(['--adapter', 'none', '--question', 'hi'])
        self.assertEqual(a.adapter, 'none')
        self.assertEqual(a.question, 'hi')

    def test_limits(self):
        a = build_arg_parser().parse_args(['--max-new-tokens', '64', '--timeout-sec', '30'])
        self.assertEqual(a.max_new_tokens, 64)
        self.assertEqual(a.timeout_sec, 30)


class PrintTurnTests(unittest.TestCase):
    def test_error_message(self):
        res = {'text': '', 'error': 'Timeout', 'elapsed_sec': 0, 'new_tokens': 0}
        # should not raise; error path prints [错误]
        print_turn('test', res)

    def test_empty_answer(self):
        res = {'text': '   ', 'error': None, 'elapsed_sec': 1.0, 'new_tokens': 3}
        print_turn('test', res)


class BaseMatchTests(unittest.TestCase):
    """Round-4.1 Task 3: LoRA base-compatibility check before loading."""

    @staticmethod
    def _write_adapter(cfg: dict) -> str:
        td = tempfile.mkdtemp(prefix='agf_base_match_')
        (Path(td) / 'adapter_config.json').write_text(json.dumps(cfg), encoding='utf-8')
        return td

    def test_real_v0_config_matches_qwen3_06b(self):
        # The real v0 adapter records base_model_name_or_path = Qwen/Qwen3-0.6B.
        repo_cfg = (Path(__file__).resolve().parents[1] / 'models'
                    / 'qwen3-0.6b-lora-v0' / 'adapter_config.json')
        if not repo_cfg.exists():
            self.skipTest('v0 adapter not present on this machine')
        ok, ab, reason = adapter_base_matches(str(repo_cfg.parent), 'Qwen/Qwen3-0.6B')
        self.assertTrue(ok, reason)
        self.assertEqual(ab, 'Qwen/Qwen3-0.6B')

    def test_cross_base_rejected(self):
        td = self._write_adapter({'base_model_name_or_path': 'Qwen/Qwen3-0.6B'})
        ok, ab, reason = adapter_base_matches(td, 'Qwen/Qwen3-4B')
        self.assertFalse(ok)
        self.assertIn('refusing to mount', reason)

    def test_no_provenance_rejected(self):
        td = self._write_adapter({'r': 8})
        ok, ab, reason = adapter_base_matches(td, 'Qwen/Qwen3-0.6B')
        self.assertFalse(ok)
        self.assertIn('no base model', reason)

    def test_trailing_slash_normalized(self):
        td = self._write_adapter({'base_model': 'Qwen/Qwen3-0.6B/'})
        ok, _, reason = adapter_base_matches(td, 'Qwen/Qwen3-0.6B')
        self.assertTrue(ok, reason)


if __name__ == '__main__':
    unittest.main()
