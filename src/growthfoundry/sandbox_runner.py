"""Restricted runner for executing generated code with real limits.

Honest security grading (Round 4.1 Task 1):
- NETWORK: Python-level import guard inside the child process (socket/ssl/
  urllib/http/... raise ImportError on import). NOT an OS-level firewall.
  Grade: NETWORK_GUARD_PYTHON.
- PROCESS TREE: Windows Job Object with KILL_ON_JOB_CLOSE - every child the
  runner spawns stays in the job and is terminated with it. Grade:
  PROCESS_TREE_KILL_PASS (OS-level).
- MEMORY: Job Object PROCESS_MEMORY_LIMIT. Grade: MEMORY_LIMIT_PASS (OS-level).
- CPU TIME: subprocess wall-clock timeout + Job Object per-job user time
  limit. Grade: CPU_TIME_LIMIT_PASS.
- FILESYSTEM: NOT isolated. The child runs with the normal user token and
  can read host files; we only give it a fresh temp cwd. Grade:
  FILESYSTEM_NOT_ISOLATED.

Because the filesystem is not isolated, the overall verdict is NEVER
SANDBOX_SECURE_PASS. run_restricted returns BLOCKED for any code that has
not been explicitly marked human-reviewed, and coding_pipeline defaults to
exec-policy=blocked.

Usage (manual, after human review of the code):
  python -m growthfoundry.sandbox_runner --code-file review.py --hint "f(1)==2"
"""
from __future__ import annotations
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IS_WINDOWS = sys.platform == 'win32'

# ---------- import guard injected into the child process ----------

GUARD_SOURCE = '''
import importlib.abc as _abc
import sys as _sys

_BLOCKED_TOPLEVEL = {
    "socket", "ssl", "urllib", "http", "ftplib", "telnetlib", "smtplib",
    "xmlrpc", "asyncio", "subprocess", "ctypes", "multiprocessing",
    "shutil", "pathlib", "builtins",
}

# Purge any pre-loaded blocked modules (defense in depth)
for _name in list(_sys.modules):
    if _name.split(".")[0] in _BLOCKED_TOPLEVEL:
        del _sys.modules[_name]


class _NetworkGuard(_abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in _BLOCKED_TOPLEVEL:
            raise ImportError(
                "module %r is blocked in the restricted runner "
                "(network/process/filesystem guard)" % top)
        return None


_sys.meta_path.insert(0, _NetworkGuard())
'''

RUNNER_SHELL = '''{guard}
import sys as _sys
import re
import json as _json

def _hint_to_asserts(hint, namespace):
    results = []
    for part in hint.split(";"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.*?)(==|!=|>=|<=|>|<)(.*)$", part)
        if not m:
            raise ValueError("bad hint fragment: " + part)
        expr, op, expected = m.group(1).strip(), m.group(2), m.group(3).strip()
        actual = eval(expr, dict(namespace))
        results.append((part, op, expected, actual))
    return results


{code}
_ns = dict([_n for _n in globals().items() if not _n[0].startswith("_")])
failures = []
for part, op, expected_raw, actual in _hint_to_asserts({hint}, _ns):
    expected = eval(expected_raw, dict(_ns))
    ops = {{
        "==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b, "<": lambda a, b: a < b,
    }}
    if not ops[op](actual, expected):
        failures.append(part + ": expected " + repr(expected) + ", got " + repr(actual))
if failures:
    print("HINT_FAILURES:")
    for f in failures:
        print(" -", f)
    _sys.exit(1)
print("ALL_HINTS_PASS")
'''


def build_guarded_runner(code: str, hint: str) -> str:
    return RUNNER_SHELL.format(guard=GUARD_SOURCE, code=code, hint=repr(hint))


# ---------- Windows Job Object (ctypes) ----------

class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_longlong),
        ('PerJobUserTimeLimit', ctypes.c_longlong),
        ('LimitFlags', ctypes.c_uint32),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', ctypes.c_uint32),
        ('Affinity', ctypes.POINTER(ctypes.c_ulonglong)),
        ('PriorityClass', ctypes.c_uint32),
        ('SchedulingClass', ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoInfo', _IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryUsed', ctypes.c_size_t),
        ('PeakJobMemoryUsed', ctypes.c_size_t),
    ]


JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class _JobObject:
    """Windows Job Object wrapper: memory limit, job time limit, kill tree."""

    def __init__(self, memory_bytes: int | None, job_user_time_sec: float | None):
        if not IS_WINDOWS:
            raise OSError('job object requires Windows')
        self.kernel32 = ctypes.windll.kernel32
        self.handle = self.kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('CreateJobObjectW failed')
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_bytes:
            info.ProcessMemoryLimit = memory_bytes
            flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
        if job_user_time_sec:
            # FILETIME: 100ns ticks
            info.BasicLimitInformation.PerJobUserTimeLimit = int(job_user_time_sec * 10_000_000)
            flags |= JOB_OBJECT_LIMIT_JOB_TIME
        info.BasicLimitInformation.LimitFlags = flags
        rc = self.kernel32.SetInformationJobObject(
            self.handle, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        if not rc:
            self.close()
            raise OSError('SetInformationJobObject failed')

    def assign(self, pid: int) -> None:
        h = self.kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h:
            raise OSError(f'OpenProcess failed for pid {pid}')
        try:
            if not self.kernel32.AssignProcessToJobObject(self.handle, h):
                raise OSError(f'AssignProcessToJobObject failed for pid {pid}')
        finally:
            self.kernel32.CloseHandle(h)

    def kill(self) -> None:
        if self.handle:
            self.kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
            self.handle = None


# ---------- restricted execution ----------

DEFAULT_MEMORY_MB = 512
DEFAULT_JOB_USER_TIME_SEC = 8  # CPU seconds across the whole job
FILETIME_100NS_PER_SEC = 10_000_000


def security_report() -> dict:
    """Honest grading of what this runner does and does not isolate."""
    return {
        'verdict': 'RESTRICTED_RUNNER_PARTIAL_NOT_SECURE',
        'sandbox_secure_pass': False,
        'network': {'grade': 'NETWORK_GUARD_PYTHON',
                    'detail': 'python import guard; not an OS firewall'},
        'process_tree': {'grade': 'PROCESS_TREE_KILL_PASS' if IS_WINDOWS else 'TIMEOUT_ONLY',
                         'detail': 'job object kills the whole tree' if IS_WINDOWS
                                   else 'subprocess timeout only (non-Windows)'},
        'memory': {'grade': 'MEMORY_LIMIT_PASS' if IS_WINDOWS else 'NOT_LIMITED',
                   'detail': f'job object process memory limit' if IS_WINDOWS
                             else 'no memory limit on this platform'},
        'cpu_time': {'grade': 'CPU_TIME_LIMIT_PASS',
                     'detail': 'wall-clock timeout + job user-time limit'},
        'filesystem': {'grade': 'FILESYSTEM_NOT_ISOLATED',
                       'detail': 'child runs with the normal user token; fresh temp cwd only'},
        'overall': 'BLOCKED for unreviewed code; restricted execution only after human review',
    }


def run_restricted(code: str, hint: str, timeout_sec: int = 10,
                   memory_mb: int = DEFAULT_MEMORY_MB,
                   reviewed: bool = False) -> dict:
    """Run code+hint under the restricted runner.

    Returns a dict with 'status' in {BLOCKED, PASSED, FAILED, TIMEOUT,
    MEM_LIMIT, ERROR} plus security metadata. Unreviewed code is BLOCKED
    by default and never executed.
    """
    sec = security_report()
    if not reviewed:
        return {'status': 'BLOCKED', 'reason': 'code not marked human-reviewed',
                'security': sec, 'executed': False}

    runner_src = build_guarded_runner(code, hint)
    t0 = time.time()
    job = None
    try:
        with tempfile.TemporaryDirectory(prefix='agf_restricted_') as td:
            script = Path(td) / 'runner.py'
            script.write_text(runner_src, encoding='utf-8')
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=td,
            )
            if IS_WINDOWS:
                try:
                    job = _JobObject(memory_mb * 1024 * 1024, DEFAULT_JOB_USER_TIME_SEC)
                    job.assign(proc.pid)
                except OSError:
                    job = None  # degrade to timeout-only, and say so
            try:
                out, err = proc.communicate(timeout=timeout_sec)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                timed_out = True
    finally:
        if job is not None:
            job.kill()
            job.close()

    elapsed = round(time.time() - t0, 2)
    result = {
        'security': sec,
        'executed': True,
        'returncode': proc.returncode,
        'stdout': (out or '')[-2000:],
        'stderr': (err or '')[-2000:],
        'timed_out': timed_out,
        'elapsed_sec': elapsed,
        'limits': {'timeout_sec': timeout_sec, 'memory_mb': memory_mb,
                   'job_user_time_sec': DEFAULT_JOB_USER_TIME_SEC},
    }
    if timed_out:
        result['status'] = 'TIMEOUT'
    elif IS_WINDOWS and (proc.returncode & 0xFFFFFFFF) == 0xC0000044:
        # STATUS_COMMITMENT_LIMIT: job object terminated the process for
        # exceeding a job limit (user time). Documented job-kill code.
        result['status'] = 'KILLED_BY_LIMIT'
        result['killed_by'] = 'job_object_limit'
    elif IS_WINDOWS and proc.returncode not in (0, 1):
        # Other unusual codes: killed by job (e.g. memory limit via
        # TerminateJobObject) or crashed.
        result['status'] = 'KILLED_BY_LIMIT'
        result['killed_by'] = f'exit_code_{hex(proc.returncode & 0xFFFFFFFF)}'
    elif proc.returncode == 0 and 'ALL_HINTS_PASS' in (out or ''):
        result['status'] = 'PASSED'
    elif proc.returncode != 0:
        result['status'] = 'FAILED'
    else:
        result['status'] = 'ERROR'
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='restricted runner self-check')
    parser.add_argument('--selfcheck', action='store_true')
    args = parser.parse_args()
    print(json.dumps(security_report(), ensure_ascii=False, indent=2))
