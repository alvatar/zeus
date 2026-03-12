"""Text/input-centric dashboard widgets."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from typing import ClassVar, cast

from textual.binding import Binding
from textual.widgets import DataTable, TextArea


def _as_binding(spec: Binding | tuple[str, ...]) -> Binding:
    """Normalize tuple-style Textual bindings into ``Binding`` objects."""
    if isinstance(spec, Binding):
        return spec
    if len(spec) >= 3:
        return Binding(spec[0], spec[1], spec[2], show=False)
    return Binding(spec[0], spec[1], show=False)


_BASE_TEXTAREA_BINDINGS: list[Binding] = [_as_binding(spec) for spec in TextArea.BINDINGS]

_TEXT_CLIPBOARD_MIME_TYPES: tuple[str, ...] = (
    "text/plain;charset=utf-8",
    "text/plain",
    "UTF8_STRING",
    "STRING",
    "TEXT",
    "text",
)

_IMAGE_CLIPBOARD_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}


class ZeusDataTable(DataTable):
    """DataTable subclass that overrides the cursor styling."""

    DEFAULT_CSS = """
    ZeusDataTable > .datatable--cursor {
        background: #cccccc;
        color: auto;
        text-style: none;
    }
    ZeusDataTable:focus > .datatable--cursor {
        background: #cccccc;
        color: auto;
        text-style: none;
    }
    ZeusDataTable > .datatable--fixed {
        background: #000000;
        color: auto;
    }
    ZeusDataTable > .datatable--fixed-cursor {
        background: #000000;
        color: auto;
        text-style: none;
    }
    ZeusDataTable:focus > .datatable--fixed-cursor {
        background: #000000;
        color: auto;
        text-style: none;
    }
    """


class ZeusTextArea(TextArea):
    """TextArea with emacs-style keybindings and kill/yank clipboard support."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = cast(
        list[Binding | tuple[str, str] | tuple[str, str, str]],
        [
            b
            for b in _BASE_TEXTAREA_BINDINGS
            if not any(
                k in b.key
                for k in (
                    "ctrl+a",
                    "ctrl+b",
                    "ctrl+e",
                    "ctrl+f",
                    "ctrl+i",
                    "ctrl+k",
                    "ctrl+m",
                    "ctrl+u",
                    "ctrl+w",
                    "ctrl+y",
                )
            )
        ]
        + [
            Binding("ctrl+a", "line_start_or_previous_line", "Line start", show=False),
            Binding("ctrl+e", "line_end_or_next_line", "Line end", show=False),
            Binding("alt+f", "cursor_word_right", "Word right", show=False),
            Binding("alt+b", "cursor_word_left", "Word left", show=False),
            Binding("alt+d", "delete_word_right", "Delete word right", show=False),
            Binding("alt+backspace", "delete_word_left", "Delete word left", show=False),
            Binding("ctrl+k", "kill_to_end_of_line_or_delete_line", "Kill to end", show=False),
            Binding("ctrl+u", "kill_to_line_start_or_clear_all", "Kill line start", show=False),
            Binding("ctrl+w", "queue_interact_or_delete_word_left", "Queue/Delete word", show=False),
            Binding("ctrl+y", "yank_kill_buffer", "Yank", show=False),
        ],
    )

    _kill_buffer: str = ""

    def action_line_start_or_previous_line(self) -> None:
        """Ctrl+A: go to line start, then previous-line start when already there."""
        line_start = self.get_cursor_line_start_location()
        if self.cursor_location == line_start:
            prev_location = self.get_cursor_up_location()
            if prev_location != self.cursor_location:
                self.move_cursor(prev_location)
                self.move_cursor(self.get_cursor_line_start_location(), record_width=False)
            return

        self.move_cursor(line_start)

    def action_line_end_or_next_line(self) -> None:
        """Ctrl+E: go to line end, then next-line end when already there."""
        line_end = self.get_cursor_line_end_location()
        if self.cursor_location == line_end:
            next_location = self.get_cursor_down_location()
            if next_location != self.cursor_location:
                self.move_cursor(next_location)
                self.move_cursor(self.get_cursor_line_end_location(), record_width=False)
            return

        self.move_cursor(line_end)

    def _notify_clipboard_unavailable(self) -> None:
        """Notify that wl-copy is unavailable; kill text stays local."""
        try:
            app = self.app
        except Exception:
            return

        message = "wl-copy unavailable; kept deleted text in local kill buffer"
        notify_force = getattr(app, "notify_force", None)
        if callable(notify_force):
            notify_force(message, timeout=3)
            return

        app.notify(message, timeout=3)

    def _copy_to_system_clipboard(self, text: str) -> None:
        """Best-effort system clipboard write; runs off the UI thread."""
        try:
            result = subprocess.run(
                ["wl-copy"],
                input=text,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, OSError):
            return

        if result.returncode != 0:
            return

    def _copy_to_system_clipboard_async(self, text: str) -> None:
        """Dispatch clipboard write asynchronously to avoid input lag."""
        thread = threading.Thread(
            target=self._copy_to_system_clipboard,
            args=(text,),
            daemon=True,
        )
        thread.start()

    def _store_kill_text(self, text: str) -> None:
        """Store deleted text in local kill buffer and system clipboard."""
        if not text:
            return

        self._kill_buffer = text
        if shutil.which("wl-copy") is None:
            self._notify_clipboard_unavailable()
            return

        self._copy_to_system_clipboard_async(text)

    def _yank_from_system_or_local_buffer(self) -> str | None:
        """Return yanked text from system clipboard, else local kill buffer."""
        text = self._paste_text_from_wl_clipboard(self._wl_paste_types())
        if text:
            return text
        if self._kill_buffer:
            return self._kill_buffer
        return None

    def action_kill_to_end_of_line_or_delete_line(self) -> None:
        """Ctrl+K: kill to end-of-line; if empty line, kill whole line."""
        if self.read_only:
            return

        action = "delete_to_end_of_line"
        if self.get_cursor_line_start_location() == self.get_cursor_line_end_location():
            action = "delete_line"
        elif (
            self.selection.start == self.selection.end == self.get_cursor_line_end_location()
        ):
            action = "delete_right"

        deleted = ""
        if action == "delete_line":
            start, end = sorted((self.selection.start, self.selection.end))
            start_row, _start_column = start
            end_row, end_column = end
            if start_row != end_row and end_column == 0 and end_row >= 0:
                end_row -= 1
            from_location = (start_row, 0)
            to_location = (end_row + 1, 0)
            deleted = self.get_text_range(from_location, to_location)
            self.action_delete_line()
        elif action == "delete_right":
            selection = self.selection
            start, end = selection
            if selection.is_empty:
                end = self.get_cursor_right_location()
            deleted = self.get_text_range(start, end)
            self.action_delete_right()
        else:
            from_location = self.selection.end
            to_location = self.get_cursor_line_end_location()
            deleted = self.get_text_range(from_location, to_location)
            self.action_delete_to_end_of_line()

        self._store_kill_text(deleted)

    def action_kill_to_line_start_or_clear_all(self) -> None:
        """Ctrl+U: keep current Zeus behavior (clear all), but kill to clipboard."""
        if self.read_only:
            return
        deleted = self.text
        self.clear()
        self._store_kill_text(deleted)

    def action_queue_interact_or_delete_word_left(self) -> None:
        """Ctrl+W: queue when appropriate, otherwise keep word-delete behavior."""
        try:
            app = self.app
        except Exception:
            self.action_delete_word_left()
            return

        screen = getattr(app, "screen", None)
        queue_modal = getattr(screen, "action_queue", None)
        if callable(queue_modal):
            queue_modal()
            return

        if getattr(self, "id", "") == "interact-input":
            queue_interact = getattr(app, "action_queue_interact", None)
            if callable(queue_interact):
                queue_interact()
                return

        self.action_delete_word_left()

    def action_yank_kill_buffer(self) -> None:
        """Ctrl+Y: yank from system clipboard, fallback to local kill buffer."""
        text = self._yank_from_system_or_local_buffer()
        if not text:
            return
        self.insert(text)

    def _wl_paste_types(self) -> list[str]:
        """Return MIME types currently offered by the Wayland clipboard."""
        try:
            r = subprocess.run(
                ["wl-paste", "--list-types"],
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []
        if r.returncode != 0:
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    def _paste_text_from_wl_clipboard(self, offered_types: list[str]) -> str | None:
        """Return clipboard text from wl-paste, or None if unavailable."""
        candidates: list[str] = []
        for mime in offered_types:
            lower = mime.lower()
            if lower.startswith("text/") or mime in {"UTF8_STRING", "STRING", "TEXT"}:
                candidates.append(mime)
        for mime in _TEXT_CLIPBOARD_MIME_TYPES:
            if mime not in candidates:
                candidates.append(mime)

        for mime in candidates:
            try:
                r = subprocess.run(
                    ["wl-paste", "--no-newline", "--type", mime],
                    capture_output=True,
                    timeout=2,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return None
            if r.returncode != 0 or not r.stdout:
                continue
            try:
                return r.stdout.decode("utf-8")
            except UnicodeDecodeError:
                continue
        return None

    def _paste_image_from_wl_clipboard(self, offered_types: list[str]) -> Path | None:
        """Save clipboard image bytes to a temp file and return its path."""
        mime: str | None = None
        for offered in offered_types:
            if offered in _IMAGE_CLIPBOARD_MIME_TO_EXT:
                mime = offered
                break
        if mime is None:
            return None

        try:
            r = subprocess.run(
                ["wl-paste", "--type", mime],
                capture_output=True,
                timeout=2,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if r.returncode != 0 or not r.stdout:
            return None

        ext = _IMAGE_CLIPBOARD_MIME_TO_EXT[mime]
        folder = Path(tempfile.gettempdir()) / "zeus-clipboard"
        suffix = int(time.time() * 1000) % 1000
        filename = f"paste-{time.strftime('%Y%m%d-%H%M%S')}-{suffix:03d}.{ext}"
        path = folder / filename

        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.stdout)
        except OSError:
            return None
        return path

    def action_paste(self) -> None:
        """Paste text from clipboard, or save images and insert their path."""
        offered_types = self._wl_paste_types()

        text = self._paste_text_from_wl_clipboard(offered_types)
        if text:
            self.insert(text)
            return

        image_path = self._paste_image_from_wl_clipboard(offered_types)
        if image_path is not None:
            self.insert(str(image_path))
            return

        # Fallback to Textual internal clipboard
        super().action_paste()
