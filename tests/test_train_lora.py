import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.train_lora import curriculum_stage, encode_records


class TestTokenizer:
    eos_token = '~'

    def __call__(self, text, *, add_special_tokens):
        return {'input_ids': list(map(ord, text))}

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
        return ''.join(f"<{message['role'][0]}>{message['content']}" for message in messages) + '<a>'


def record(*parts, task_type=None):
    return {'source_id': 'test-record', 'task_type': task_type, 'messages': [
        {'role': role, 'content': content}
        for role, content in zip(['user', 'assistant'] * (len(parts) // 2), parts)
    ]}


def decode(ids):
    return ''.join(map(chr, ids))


class TrainEncodingTests(unittest.TestCase):
    def test_each_assistant_reply_is_supervised_once(self):
        sample = record('first prompt', 'first reply', 'follow-up', 'second reply')
        rows, counts = encode_records([sample], TestTokenizer(), 100)
        self.assertEqual(counts['answer_turns'], 2)
        for row, prompt, reply in zip(rows, ('<u>first prompt<a>', '<u>first prompt<a>first reply<u>follow-up<a>'),
                                      ('first reply~', 'second reply~')):
            self.assertEqual(decode(row['input_ids']), prompt + reply)
            self.assertEqual(row['labels'], [-100] * len(prompt) + list(map(ord, reply)))
            self.assertEqual(row['attention_mask'], [1] * len(row['labels']))

    def test_discards_whole_old_turns_before_truncating_target(self):
        sample = record('first prompt', 'first reply', 'follow-up', 'second reply')
        rows, counts = encode_records([sample], TestTokenizer(), 31)
        self.assertEqual(decode(rows[1]['input_ids']), '<u>follow-up<a>second reply~')
        self.assertEqual(counts['shortened_history_turns'], 1)
        self.assertEqual(counts['truncated_answer_turns'], 0)

    def test_truncated_answer_does_not_teach_premature_eos(self):
        rows, counts = encode_records([record('ask', 'long answer')], TestTokenizer(), 13)
        self.assertEqual(decode(rows[0]['labels'][9:]), 'long')
        self.assertEqual(counts['truncated_answer_turns'], 1)
        with self.assertRaisesRegex(ValueError, 'test-record turn 1'):
            encode_records([record('long prompt', 'reply')], TestTokenizer(), 10)

    def test_curriculum_places_generation_before_debug_and_multiturn(self):
        debug = record('bug', 'fix', task_type='debug')
        generate = record('task', 'code', task_type='code_gen')
        legacy = record('question', 'answer')
        multi = record('task', 'code', 'follow-up', 'answer')
        self.assertEqual(sorted([debug, multi, legacy, generate], key=curriculum_stage),
                         [generate, legacy, debug, multi])

    def test_phase_two_dry_run_preserves_data_gate_and_configures_sweep(self):
        result = subprocess.run(
            [sys.executable, 'scripts/train_lora.py', '--dataset', 'data/seed/sft_examples_v4.jsonl',
             '--lr-search', '--rank', '16', '--early-stop', '--curriculum', '--dry-run'],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report['status'], 'CONFIG_VALIDATED_ONLY_NOT_TRAINED')
        self.assertEqual((report['train'], report['eval']), (835, 54))
        self.assertEqual(report['train_answer_turns'], 1045)
        self.assertEqual((report['rank'], report['alpha'], report['max_length']), (16, 32, 512))
        self.assertEqual(report['learning_rates'], [5e-5, 1e-4, 2e-4, 5e-4])
        self.assertGreater(report['epochs'], report['patience'])


if __name__ == '__main__':
    unittest.main()
