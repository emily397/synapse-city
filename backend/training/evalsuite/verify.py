"""Execution verification: extract the model's answer/code and check it.

Code tasks run in a subprocess sandbox: isolated interpreter (-I), temp cwd,
5s timeout, no environment. No network syscalls are provided by the tasks and
the harness never imports network modules; the timeout bounds any attempt.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile

SANDBOX_TIMEOUT = 5.0

_CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)
_ANSWER = re.compile(r"ANSWER:\s*(.+)")


def extract_code(text: str) -> str | None:
    blocks = _CODE_BLOCK.findall(text or "")
    for b in reversed(blocks):            # last block wins
        if "def solve" in b:
            return b
    if blocks:
        return blocks[-1]
    m = re.search(r"(def solve\(.*)", text or "", re.DOTALL)
    return m.group(1) if m else None


def extract_answer(text: str) -> str | None:
    hits = _ANSWER.findall(text or "")
    return hits[-1].strip() if hits else None


def _norm(s: str) -> str:
    return re.sub(r"[\s'\"`.]+", "", (s or "").strip().lower())


def run_sandbox(code: str, check: str) -> tuple[bool, str]:
    harness = code + "\n\n" + check + "\nprint('PASS')\n"
    with tempfile.TemporaryDirectory() as td:
        try:
            p = subprocess.run(
                [sys.executable, "-I", "-c", harness],
                capture_output=True, text=True, timeout=SANDBOX_TIMEOUT,
                cwd=td, env={},
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:                      # noqa: BLE001
            return False, f"sandbox error: {e}"
    ok = p.returncode == 0 and "PASS" in p.stdout
    return ok, (p.stderr or p.stdout or "")[-400:]


def verify(task: dict, model_output: str) -> tuple[bool, str]:
    """Return (passed, detail) for a task dict from families.make_task."""
    if task["kind"] == "code":
        code = extract_code(model_output)
        if not code:
            return False, "no code block found"
        return run_sandbox(code, task["check"])
    ans = extract_answer(model_output)
    if ans is None:
        return False, "no ANSWER: line"
    return _norm(ans) == _norm(task["expected"]), f"got {ans!r}"
