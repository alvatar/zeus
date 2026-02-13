"""Custom widgets: ZeusDataTable, UsageBar, ZeusTextArea."""

from __future__ import annotations

import subprocess

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Static, TextArea
from rich.text import Text


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
    """


class ZeusTextArea(TextArea):
    """TextArea with emacs-style alt keybindings and system clipboard paste."""
    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("alt+f", "cursor_word_right", "Word right", show=False),
        Binding("alt+b", "cursor_word_left", "Word left", show=False),
        Binding("ctrl+l", "clear_all", "Clear", show=False),
    ]

    def action_clear_all(self) -> None:
        """Clear entire text area."""
        self.clear()

    def action_paste(self) -> None:
        """Paste from system clipboard (wl-paste for Wayland)."""
        try:
            r = subprocess.run(
                ["wl-paste", "--no-newline"],
                capture_output=True, text=True, timeout=2,
            )
            if r.returncode == 0 and r.stdout:
                self.insert(r.stdout)
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        # Fallback to Textual internal clipboard
        super().action_paste()


class UsageBar(Static):
    """A labeled progress bar showing a percentage."""
    pct: reactive[float] = reactive(0.0)
    label_text: reactive[str] = reactive("")
    extra_text: reactive[str] = reactive("")

    def __init__(self, label: str, **kwargs: str) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
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
