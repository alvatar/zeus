"""Tests for Zeus dashboard custom widgets."""

from pathlib import Path
import subprocess
from typing import Any

import zeus.dashboard.widgets as widgets
from zeus.dashboard.widgets import ZeusTextArea


def test_action_paste_inserts_text_from_wl_clipboard(monkeypatch):
    ta = ZeusTextArea("")

    def fake_run(
        command: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if command == ["wl-paste", "--list-types"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="text/plain\n", stderr="",
            )
        if command == ["wl-paste", "--no-newline", "--type", "text/plain"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=b"hello from clipboard", stderr=b"",
            )
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(widgets.subprocess, "run", fake_run)

    ta.action_paste()

    assert ta.text == "hello from clipboard"


def test_action_paste_saves_image_and_inserts_file_path(monkeypatch, tmp_path):
    ta = ZeusTextArea("")
    image_bytes = b"\x89PNG\r\n\x1a\nPNGDATA"

    def fake_run(
        command: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if command == ["wl-paste", "--list-types"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="image/png\n", stderr="",
            )
        if command[:3] == ["wl-paste", "--no-newline", "--type"]:
            return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"")
        if command == ["wl-paste", "--type", "image/png"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=image_bytes, stderr=b"",
            )
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(widgets.subprocess, "run", fake_run)
    monkeypatch.setattr(widgets.tempfile, "gettempdir", lambda: str(tmp_path))

    ta.action_paste()

    pasted_path = Path(ta.text)
    assert pasted_path.exists()
    assert pasted_path.suffix == ".png"
    assert pasted_path.read_bytes() == image_bytes


def test_text_area_does_not_keep_global_ctrl_bindings() -> None:
    keys = [binding.key for binding in ZeusTextArea.BINDINGS]
    assert "ctrl+b" not in keys
    assert "ctrl+i" not in keys
    assert "ctrl+m" not in keys
