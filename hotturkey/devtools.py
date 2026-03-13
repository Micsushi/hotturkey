# cli commands for development (lint, test, CI)

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hotturkey.logger import log_event

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> int:
    """Run a subprocess command, streaming output, and return its exit code."""
    print(f"+ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT))


def lint() -> None:
    """Run Black on the repo and then pylint with the project configuration."""
    code = _run([sys.executable, "-m", "black", "."])
    if code != 0:
        raise SystemExit(code)
    code = _run(
        [sys.executable, "-m", "pylint", "hotturkey/", "--rcfile=pyproject.toml"]
    )
    raise SystemExit(code)


def test() -> None:
    """Run the test suite with pytest, logging START/STOP-style markers."""
    log_event("SYSTEM", message="tests: starting")
    code = _run([sys.executable, "-m", "pytest", "-v"])
    if code == 0:
        log_event("SYSTEM", message="tests: finished ok")
    else:
        log_event("SYSTEM", message=f"tests: FAILED exit_code={code}")
    raise SystemExit(code)


def ci() -> None:
    """Run format + lint + tests, like the CI workflow, with markers."""
    log_event("SYSTEM", message="ci: format+lint+tests starting")
    code = _run([sys.executable, "-m", "black", "."])
    if code != 0:
        log_event("SYSTEM", message=f"ci: black failed exit_code={code}")
        raise SystemExit(code)
    code = _run(
        [sys.executable, "-m", "pylint", "hotturkey/", "--rcfile=pyproject.toml"]
    )
    if code != 0:
        log_event("SYSTEM", message=f"ci: pylint failed exit_code={code}")
        raise SystemExit(code)
    log_event("SYSTEM", message="ci: running tests")
    code = _run([sys.executable, "-m", "pytest", "-v"])
    if code == 0:
        log_event("SYSTEM", message="ci: finished ok")
    else:
        log_event("SYSTEM", message=f"ci: tests FAILED exit_code={code}")
    raise SystemExit(code)
