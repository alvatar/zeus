"""Custom widgets: ZeusDataTable, UsageBar, ZeusTextArea."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time
from typing import ClassVar, cast

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Static, TextArea
from rich.text import Text


def _as_binding(spec: Binding | tuple[str, ...]) -> Binding:
    """Normalize tuple-style Textual bindings into ``Binding`` objects."""
    if isinstance(spec, Binding):
        return spec
    if len(spec) >= 3:
        return Binding(spec[0], spec[1], spec[2], show=False)
    return Binding(spec[0], spec[1], show=False)


_BASE_TEXTAREA_BINDINGS: list[Binding] = [
    _as_binding(spec) for spec in TextArea.BINDINGS
]

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
    """TextArea with emacs-style alt keybindings and system clipboard paste."""
    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = cast(
        list[Binding | tuple[str, str] | tuple[str, str, str]],
        [
            b for b in _BASE_TEXTAREA_BINDINGS
            if not any(k in b.key for k in ("ctrl+u", "ctrl+f", "ctrl+w"))
        ] + [
            Binding("alt+f", "cursor_word_right", "Word right", show=False),
            Binding("alt+b", "cursor_word_left", "Word left", show=False),
            Binding("alt+d", "delete_word_right", "Delete word right", show=False),
            Binding("alt+backspace", "delete_word_left", "Delete word left", show=False),
            Binding("ctrl+u", "clear_all", "Clear", show=False),
            Binding("ctrl+y", "paste", "Paste", show=False),
        ],
    )

    def action_clear_all(self) -> None:
        """Clear entire text area."""
        self.clear()

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


class UsageBar(Static):
    """A labeled progress bar showing a percentage."""
    pct: reactive[float] = reactive(0.0)
    label_text: reactive[str] = reactive("")
    extra_text: reactive[str] = reactive("")

    def __init__(
        self,
        label: str,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self.label_text = label

    def render(self) -> Text:
        pct: float = self.pct
        width: int = 12
        filled: int = round((min(100, max(0, pct)) / 100) * width)
        if pct >= 90:
            color = "#ff3333"
        elif pct >= 80:
            color = "#ff8800"
        else:
            color = "#00d7d7"
        bar_empty: str = "#555555"

        pct_str: str = f"{pct:.0f}%"
        pct_field: str = pct_str.rjust(4)

        extra_width: int = 7
        extra: str = (self.extra_text or "").ljust(extra_width)

        t = Text()
        t.append(f"{self.label_text} ", style="#447777")
        t.append("█" * filled, style=color)
        t.append("░" * (width - filled), style=bar_empty)
        t.append(f"{pct_field}", style=f"bold {color}")
        t.append(f" {extra}", style="#447777")
        return t
