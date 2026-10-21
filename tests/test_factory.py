import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.score import score_candidate, rank_candidates
from growthfoundry.builder import build_product, build_candidates
from growthfoundry.store import Store

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


class ScoreTests(unittest.TestCase):
    def test_score_bounds(self):
        # extreme inputs never leave 0..100
        hi = score_candidate({'id': 'a', 'license': 'MIT',
                              'metadata': {'stars': 10**9, 'pushed_at': '2026-10-21T00:00:00Z'}}, now=NOW)
        lo = score_candidate({'id': 'b', 'license': 'UNKNOWN',
                              'metadata': {'stars': 0, 'pushed_at': '1900-01-01T00:00:00Z',
                                           'archived': True, 'fork': True}}, now=NOW)
        self.assertLessEqual(hi['score'], 100)
        self.assertGreaterEqual(lo['score'], 0)

    def test_license_grade_affects_score(self):
        mit = score_candidate({'id': 'a', 'license': 'MIT',
                               'metadata': {'stars': 1000, 'pushed_at': '2026-10-01T00:00:00Z'}}, now=NOW)
        unk = score_candidate({'id': 'b', 'license': 'UNKNOWN',
                               'metadata': {'stars': 1000, 'pushed_at': '2026-10-01T00:00:00Z'}}, now=NOW)
        self.assertGreater(mit['score'], unk['score'])

    def test_recent_push_beats_stale(self):
        fresh = score_candidate({'id': 'a', 'license': 'MIT',
                                 'metadata': {'stars': 100, 'pushed_at': '2026-10-01T00:00:00Z'}}, now=NOW)
        stale = score_candidate({'id': 'b', 'license': 'MIT',
                                 'metadata': {'stars': 100, 'pushed_at': '2019-01-01T00:00:00Z'}}, now=NOW)
        self.assertGreater(fresh['score'], stale['score'])

    def test_archived_and_fork_penalties(self):
        base = {'id': 'a', 'license': 'MIT', 'metadata': {'stars': 100, 'pushed_at': '2026-10-01T00:00:00Z'}}
        clean = score_candidate(base, now=NOW)
        archived = score_candidate(dict(base, metadata=dict(base['metadata'], archived=True)), now=NOW)
        forked = score_candidate(dict(base, metadata=dict(base['metadata'], fork=True)), now=NOW)
        self.assertGreater(clean['score'], archived['score'])
        self.assertGreater(clean['score'], forked['score'])

    def test_ranking_order_and_reasons(self):
        ranked = rank_candidates([
            {'id': 'b', 'license': 'MIT', 'metadata': {'stars': 100, 'pushed_at': '2026-10-01T00:00:00Z'}},
            {'id': 'a', 'license': 'MIT', 'metadata': {'stars': 100, 'pushed_at': '2026-10-01T00:00:00Z'}},
            {'id': 'c', 'license': 'UNKNOWN', 'metadata': {'stars': 5, 'pushed_at': '2000-01-01T00:00:00Z',
                                                           'archived': True, 'fork': True}},
        ], now=NOW)
        scores = [r['score'] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for r in ranked:
            self.assertTrue(r['reasons'])
            self.assertTrue(0 <= r['score'] <= 100)

    def test_deterministic(self):
        cand = {'id': 'x', 'license': 'Apache-2.0', 'metadata': {'stars': 999, 'pushed_at': '2026-05-05T00:00:00Z'}}
        self.assertEqual(score_candidate(cand, now=NOW), score_candidate(cand, now=NOW))


class BuilderTests(unittest.TestCase):
    def _seed(self, db):
        store = Store(db)
        store.put({'id': 'c1', 'title': 'T1', 'license': 'MIT', 'source_url': 'https://github.com/a/b'},
                  'REVIEW', 'test seed')
        store.put({'id': 'c2', 'title': 'T2', 'license': 'NO-LICENSE', 'source_url': 'https://github.com/c/d'},
                  'BLOCKED', 'test seed')
        store.close()

    def _cand(self, cid):
        return {'id': cid, 'title': 'T', 'license': 'MIT', 'source_url': 'https://github.com/a/b'}

    def test_build_artifacts_exist_and_state_advanced(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db = d / 'state.db'
            self._seed(db)
            res = build_product(self._cand('c1'), db, d / 'packs')
            self.assertEqual(res['final_state'], 'READY_FOR_REVIEW')
            self.assertTrue(res['self_authored'])
            for artifact in res['artifacts']:
                p = Path(artifact)
                self.assertTrue(p.is_file())
                self.assertGreater(p.stat().st_size, 0)
            for name in ('README.md', 'checklist.md', 'DEPLOY_GUIDE.md'):
                self.assertIn(name, [Path(a).name for a in res['artifacts']])
            con = sqlite3.connect(db)
            states = [r[0] for r in con.execute(
                "SELECT state FROM events WHERE candidate_id='c1' ORDER BY id")]
            con.close()
            self.assertEqual(states, ['REVIEW', 'BUILDING', 'TESTING', 'READY_FOR_REVIEW'])

    def test_blocked_candidate_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db = d / 'state.db'
            self._seed(db)
            with self.assertRaises(PermissionError):
                build_product(self._cand('c2'), db, d / 'packs')

    def test_unknown_candidate_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db = d / 'state.db'
            self._seed(db)
            with self.assertRaises(ValueError):
                build_product(self._cand('nope'), db, d / 'packs')

    def test_build_candidates_skips_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db = d / 'state.db'
            self._seed(db)
            out = build_candidates([self._cand('c1'), self._cand('c2')], db, d / 'packs')
            self.assertEqual(len(out['built']), 1)
            self.assertEqual(out['built'][0]['candidate_id'], 'c1')
            self.assertEqual(len(out['skipped']), 1)
            self.assertEqual(out['skipped'][0]['candidate_id'], 'c2')
            self.assertFalse(out['publish_enabled'])

    def test_no_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            db = d / 'state.db'
            self._seed(db)
            res = build_product(self._cand('c1'), db, d / 'packs')
            self.assertFalse(res['publish_enabled'])


if __name__ == '__main__':
    unittest.main()
