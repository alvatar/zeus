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


def test_text_area_ctrl_a_e_k_u_y_are_custom_bindings() -> None:
    bindings = {binding.key: binding for binding in ZeusTextArea.BINDINGS}

    assert bindings["ctrl+a"].action == "line_start_or_previous_line"
    assert bindings["ctrl+e"].action == "line_end_or_next_line"
    assert bindings["ctrl+k"].action == "kill_to_end_of_line_or_delete_line"
    assert bindings["ctrl+u"].action == "kill_to_line_start_or_clear_all"
    assert bindings["ctrl+y"].action == "yank_kill_buffer"


def test_ctrl_a_moves_to_line_start_then_previous_line_start() -> None:
    ta = ZeusTextArea("alpha\nbeta\ngamma")
    ta.move_cursor((1, 2))

    ta.action_line_start_or_previous_line()
    assert ta.cursor_location == (1, 0)

    ta.action_line_start_or_previous_line()
    assert ta.cursor_location == (0, 0)


def test_ctrl_e_moves_to_line_end_then_next_line_end() -> None:
    ta = ZeusTextArea("alpha\nbeta\ngamma")
    ta.move_cursor((0, 2))

    ta.action_line_end_or_next_line()
    assert ta.cursor_location == (0, 5)

    ta.action_line_end_or_next_line()
    assert ta.cursor_location == (1, 4)


def test_ctrl_u_kills_all_text_and_copies_to_wl_copy(monkeypatch) -> None:
    ta = ZeusTextArea("hello")

    copied: list[str] = []
    monkeypatch.setattr(widgets.shutil, "which", lambda _cmd: "/usr/bin/wl-copy")
    monkeypatch.setattr(
        ta,
        "_copy_to_system_clipboard_async",
        lambda text: copied.append(text),
    )

    ta.action_kill_to_line_start_or_clear_all()

    assert ta.text == ""
    assert ta._kill_buffer == "hello"
    assert copied == ["hello"]


def test_ctrl_y_falls_back_to_local_kill_buffer_when_clipboard_empty(monkeypatch) -> None:
    ta = ZeusTextArea("")
    ta._kill_buffer = "killed"

    monkeypatch.setattr(ta, "_wl_paste_types", lambda: [])
    monkeypatch.setattr(ta, "_paste_text_from_wl_clipboard", lambda offered: None)

    ta.action_yank_kill_buffer()

    assert ta.text == "killed"


def test_ctrl_u_notifies_when_wl_copy_missing(monkeypatch) -> None:
    ta = ZeusTextArea("hello")

    monkeypatch.setattr(widgets.shutil, "which", lambda _cmd: None)

    notified: list[bool] = []
    monkeypatch.setattr(ta, "_notify_clipboard_unavailable", lambda: notified.append(True))

    ta.action_kill_to_line_start_or_clear_all()

    assert ta._kill_buffer == "hello"
    assert notified == [True]


def test_widgets_module_exposes_clipboard_patch_targets() -> None:
    import zeus.dashboard.widgets_text as widgets_text

    assert widgets.subprocess is widgets_text.subprocess
    assert widgets.shutil is widgets_text.shutil
    assert widgets.tempfile is widgets_text.tempfile
