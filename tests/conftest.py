"""Pytest global setup for isolated Zeus test state.

This prevents tests from mutating live Zeus runtime state files in /tmp.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile


_TEST_ROOT = Path(tempfile.mkdtemp(prefix="zeus-pytest-state-"))
_TEST_STATE_DIR = _TEST_ROOT / "state"
_TEST_MESSAGE_TMP_DIR = _TEST_ROOT / "message-tmp"

_TEST_STATE_DIR.mkdir(parents=True, exist_ok=True)
_TEST_MESSAGE_TMP_DIR.mkdir(parents=True, exist_ok=True)

# Force test process (and imported Zeus modules) to use isolated paths.
os.environ["ZEUS_STATE_DIR"] = str(_TEST_STATE_DIR)
os.environ["ZEUS_MESSAGE_TMP_DIR"] = str(_TEST_MESSAGE_TMP_DIR)


@atexit.register
def _cleanup_test_state() -> None:
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
