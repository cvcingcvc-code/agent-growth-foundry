"""Unit tests for sandbox_runner.py (real subprocesses, no GPU/model).

Covers: BLOCKED default, restricted execution, network guard, memory limit,
job user-time limit, process-tree kill, and the honest security report that
never claims SANDBOX_SECURE_PASS.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.sandbox_runner import (
    _JobObject, build_guarded_runner, run_restricted, security_report,
)


class SecurityReportTests(unittest.TestCase):

    def test_never_claims_secure(self):
        rep = security_report()
        self.assertFalse(rep['sandbox_secure_pass'])
        self.assertNotEqual(rep['verdict'], 'SANDBOX_SECURE_PASS')

    def test_filesystem_not_isolated(self):
        rep = security_report()
        self.assertEqual(rep['filesystem']['grade'], 'FILESYSTEM_NOT_ISOLATED')

    def test_network_guard_graded(self):
        rep = security_report()
        self.assertEqual(rep['network']['grade'], 'NETWORK_GUARD_PYTHON')


class BlockedTests(unittest.TestCase):

    def test_unreviewed_code_blocked_not_executed(self):
        r = run_restricted('x = 1', 'x==1')
        self.assertEqual(r['status'], 'BLOCKED')
        self.assertFalse(r['executed'])

    def test_reviewed_flag_required(self):
        r = run_restricted('def f():\n    return 1', 'f()==1', reviewed=False)
        self.assertEqual(r['status'], 'BLOCKED')


class RunnerTests(unittest.TestCase):

    def test_correct_code_passes(self):
        r = run_restricted('def add(a, b):\n    return a + b', 'add(1,2)==3', reviewed=True)
        self.assertEqual(r['status'], 'PASSED')
        self.assertTrue(r['executed'])

    def test_wrong_result_fails(self):
        r = run_restricted('def add(a, b):\n    return a + b + 1', 'add(1,2)==3', reviewed=True)
        self.assertEqual(r['status'], 'FAILED')

    def test_timeout_kills(self):
        r = run_restricted('def f(n):\n    while 1:\n        n += 1', 'f(1)==1',
                           timeout_sec=3, reviewed=True)
        self.assertEqual(r['status'], 'TIMEOUT')

    def test_network_guard_blocks_socket(self):
        r = run_restricted('import socket\ndef f():\n    return 1', 'f()==1', reviewed=True)
        self.assertEqual(r['status'], 'FAILED')
        self.assertIn('blocked', r['stderr'])

    def test_subprocess_import_blocked(self):
        r = run_restricted('import subprocess\ndef f():\n    return 1', 'f()==1', reviewed=True)
        self.assertIn('blocked', r['stderr'])

    def test_memory_limit_enforced(self):
        # 300MB incremental allocation under a 64MB job limit dies fast.
        code = 'buf = []\nfor i in range(20):\n    buf.append(bytearray(16 * 1024 * 1024))\ndef f():\n    return 1'
        r = run_restricted(code, 'f()==1', memory_mb=64, reviewed=True)
        self.assertIn(r['status'], ('FAILED', 'KILLED_BY_LIMIT'))
        self.assertLess(r['elapsed_sec'], 10)


class JobObjectTests(unittest.TestCase):

    def test_job_time_limit_kills_cpu_burn(self):
        import subprocess, time
        if not sys.platform == 'win32':
            self.skipTest('job object requires Windows')
        code = 'x = 0\nwhile 1:\n    x += 1'
        proc = subprocess.Popen([sys.executable, '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        job = _JobObject(None, 2.0)
        job.assign(proc.pid)
        t0 = time.time()
        try:
            proc.communicate(timeout=30)
            to = False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            to = True
        finally:
            job.kill()
            job.close()
        elapsed = time.time() - t0
        self.assertFalse(to, 'job user-time limit should kill before wall timeout')
        self.assertLess(elapsed, 20, 'CPU burn should die well before 30s wall cap')

    def test_kill_on_job_close(self):
        import subprocess, time
        if not sys.platform == 'win32':
            self.skipTest('job object requires Windows')
        code = 'import time\ntime.sleep(30)'
        proc = subprocess.Popen([sys.executable, '-c', code],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        job = _JobObject(None, None)
        job.assign(proc.pid)
        time.sleep(0.5)
        job.kill()
        job.close()
        proc.communicate(timeout=10)
        self.assertNotEqual(proc.returncode, 0, 'sleeping child must be terminated by job kill')


if __name__ == '__main__':
    unittest.main()
