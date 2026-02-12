"""Custom widgets: ZeusDataTable, UsageBar."""

from textual.reactive import reactive
from textual.widgets import DataTable, Static
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


class UsageBar(Static):
    """A labeled progress bar showing a percentage."""
    pct = reactive(0.0)
    label_text = reactive("")
    extra_text = reactive("")

    def __init__(self, label: str, **kwargs):
        super().__init__(**kwargs)
        self.label_text = label

    def render(self) -> Text:
        pct = self.pct
        width = 12
        filled = round((min(100, max(0, pct)) / 100) * width)
        if pct >= 90:
            color = "#ff3333"
        elif pct >= 80:
            color = "#ff8800"
        else:
            color = "#00d7d7"
        bar_empty = "#555555"

        pct_str = f"{pct:.0f}%"
        pct_field = pct_str.rjust(4)

        extra_width = 7
        extra = (self.extra_text or "")
        extra = f"{extra.ljust(extra_width)}"

        t = Text()
        t.append(f"{self.label_text} ", style="#447777")
        t.append("█" * filled, style=color)
        t.append("░" * (width - filled), style=bar_empty)
        t.append(f"{pct_field}", style=f"bold {color}")
        t.append(f" {extra}", style="#447777")
        return t
