"""Custom widgets: ZeusDataTable, UsageBar, ZeusTextArea."""

from __future__ import annotations

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
    """TextArea with emacs-style alt keybindings."""
    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("alt+f", "cursor_word_right", "Word right", show=False),
        Binding("alt+b", "cursor_word_left", "Word left", show=False),
    ]


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
