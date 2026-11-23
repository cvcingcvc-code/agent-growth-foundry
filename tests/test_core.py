import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from growthfoundry.dataset import read_approved, validate_record
from growthfoundry.policy import assess_license
from growthfoundry.pipeline import run_candidates
from growthfoundry.store import Store


class CoreTests(unittest.TestCase):
    def test_license_closed_default(self):
        self.assertEqual(assess_license('NO-LICENSE').status, 'BLOCKED')
        self.assertEqual(assess_license('MIT').status, 'REVIEW')
        self.assertEqual(assess_license('GPL-3.0').status, 'REVIEW')
        self.assertEqual(assess_license('CC-BY-NC-4.0').status, 'BLOCKED')

    def test_sft_gate(self):
        split = read_approved(ROOT / 'data/seed/sft_examples.jsonl')
        self.assertGreaterEqual(len(split['train']), 4)
        self.assertGreaterEqual(len(split['eval']), 2)
        bad = dict(split['train'][0])
        bad['rights'] = 'UNKNOWN'
        with self.assertRaises(ValueError):
            validate_record(bad)

    def test_sqlite_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            report = run_candidates(ROOT / 'data/seed/candidates.jsonl', d / 'state.db', d / 'report.json')
            self.assertEqual(report['count'], 3)
            self.assertFalse(report['publish_enabled'])
            self.assertEqual(report['items'][1]['state'], 'BLOCKED')
            self.assertTrue((d / 'report.json').exists())

    def test_store_advance_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'state.db'
            store = Store(db_path)
            item = {'id': 'c-1', 'title': 'Test Item', 'license': 'MIT', 'source_url': 'https://github.com/a/b'}
            store.put(item, 'REVIEW', 'initial review')
            items = store.list_items()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]['state'], 'REVIEW')

            # advance state
            store.advance_state('c-1', 'BUILDING', reason='start building')
            items = store.list_items()
            self.assertEqual(items[0]['state'], 'BUILDING')
            self.assertEqual(items[0]['reason'], 'start building')

            # verify event log
            events = store.db.execute("SELECT state, note FROM events WHERE candidate_id='c-1' ORDER BY id").fetchall()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0][0], 'REVIEW')
            self.assertEqual(events[1][0], 'BUILDING')

            # invalid state
            with self.assertRaises(ValueError):
                store.advance_state('c-1', 'INVALID_STATE')

            # unknown candidate
            with self.assertRaises(KeyError):
                store.advance_state('c-unknown', 'BUILDING')
            store.close()


class ConnectorContractTests(unittest.TestCase):
    def test_disallows_unexpected_repo_identifiers(self):
        from growthfoundry.github_collector import get_repo_metadata
        for slug in ['https://github.com/a/b', 'a/b/../../evil', 'a b/c', 'a/b?bad=1']:
            with self.assertRaises(ValueError):
                get_repo_metadata(slug)

    def test_experience_not_automatically_training_eligible(self):
        from growthfoundry.experience import record_experience
        with tempfile.TemporaryDirectory() as folder:
            r = record_experience(Path(folder) / 'events.jsonl', task_id='B0', lesson='A model can overfit', test_evidence='local report', approved=True)
            self.assertTrue(r['approved_for_learning'])
            self.assertFalse(r['training_eligible'])

    def test_eval_comparison_report_assembly(self):
        from scripts.eval_lora import build_comparison_report
        records = [{'source_id': 's-1', 'messages': [{'role': 'user', 'content': 'Q1'}, {'role': 'assistant', 'content': 'R1'}]}]
        report = build_comparison_report(records, ['base out'], ['lora out'], 'models/adapter-x', 'GPU test')
        self.assertEqual(report['status'], 'BASE_VS_LORA_COMPARISON_ONLY_NOT_SIGNIFICANCE_CLAIM')
        self.assertEqual(report['samples'], 1)
        self.assertEqual(report['items'][0]['base_answer'], 'base out')
        self.assertEqual(report['items'][0]['lora_answer'], 'lora out')
        self.assertIn('no statistically significant', report['limitation'].lower())
        with self.assertRaises(AssertionError):
            build_comparison_report(records, [], ['lora out'], 'm', 'n')


if __name__ == '__main__':
    unittest.main()
