"""Chart/visual helper widgets and render helpers."""

from __future__ import annotations

from collections.abc import Mapping

from textual.reactive import reactive
from textual.widgets import Static
from rich.text import Text

from ..settings import SETTINGS


# ── Braille sparkline ─────────────────────────────────────────────────

_BRAILLE_BASE = 0x2800
# Cumulative dot patterns for left/right columns, heights 0-4 (bottom up)
_LEFT_FILL = (0x00, 0x40, 0x44, 0x46, 0x47)
_RIGHT_FILL = (0x00, 0x80, 0xA0, 0xB0, 0xB8)


def braille_sparkline(
    values: list[float],
    width: int = 25,
) -> Text:
    """Render values (0–100) as a colored braille sparkline."""
    n = width * 2
    if len(values) >= n:
        vals = values[-n:]
    else:
        vals = [0.0] * (n - len(values)) + list(values)

    t = Text()
    for i in range(0, len(vals), 2):
        v1 = max(0.0, min(100.0, vals[i]))
        v2 = max(0.0, min(100.0, vals[i + 1]))
        h1 = min(4, round(v1 / 100.0 * 4))
        h2 = min(4, round(v2 / 100.0 * 4))
        code = _BRAILLE_BASE | _LEFT_FILL[h1] | _RIGHT_FILL[h2]
        avg = (v1 + v2) / 2.0
        t.append(chr(code), style=_gradient_color(avg))
    return t


def braille_sparkline_markup(
    values: list[float],
    width: int = 25,
) -> str:
    """Render values (0–100) as Rich markup string of colored braille chars."""
    n = width * 2
    if len(values) >= n:
        vals = values[-n:]
    else:
        vals = [0.0] * (n - len(values)) + list(values)

    parts: list[str] = []
    for i in range(0, len(vals), 2):
        v1 = max(0.0, min(100.0, vals[i]))
        v2 = max(0.0, min(100.0, vals[i + 1]))
        h1 = min(4, round(v1 / 100.0 * 4))
        h2 = min(4, round(v2 / 100.0 * 4))
        code = _BRAILLE_BASE | _LEFT_FILL[h1] | _RIGHT_FILL[h2]
        avg = (v1 + v2) / 2.0
        color = _gradient_color(avg)
        parts.append(f"[{color}]{chr(code)}[/]")
    return "".join(parts)


# State → braille height 0–3
_STATE_SPARK_HEIGHT: dict[str, int] = {
    "WORKING": 3,
    "WAITING": 2,
    "IDLE": 1,
}

# Lifted fill tables — skip bottom row (row 3), use rows 2,1,0 only
_LEFT_FILL_UP = (0x00, 0x04, 0x06, 0x07)
_RIGHT_FILL_UP = (0x00, 0x20, 0x30, 0x38)


def _default_state_spark_colors() -> dict[str, str]:
    """Default sparkline colors mapped from configured state colors."""
    return {
        "WORKING": SETTINGS.state_colors.working,
        "WAITING": SETTINGS.state_colors.waiting,
        "IDLE": SETTINGS.state_colors.idle,
    }


def state_sparkline_markup(
    states: list[str],
    width: int = 25,
    colors: Mapping[str, str] | None = None,
) -> str:
    """Render state labels as a colored braille sparkline."""
    palette: Mapping[str, str] = colors or _default_state_spark_colors()

    n = width * 2
    real = list(states[-n:]) if len(states) >= n else list(states)
    if len(real) % 2 == 1:
        real = real[1:]  # drop oldest so pairings stay stable
    pad = n - len(real)
    vals = [""] * pad + real

    parts: list[str] = []
    for i in range(0, len(vals), 2):
        s1, s2 = vals[i], vals[i + 1]
        c1 = palette.get(s1, "#222222")
        c2 = palette.get(s2, "#222222")
        h1 = _STATE_SPARK_HEIGHT.get(s1, 0)
        h2 = _STATE_SPARK_HEIGHT.get(s2, 0)
        code = _BRAILLE_BASE | _LEFT_FILL_UP[h1] | _RIGHT_FILL_UP[h2]
        if s1 == s2:
            color = c1
        elif "WAITING" in (s1, s2):
            color = palette.get("WAITING", "#222222")
        elif "WORKING" in (s1, s2):
            color = palette.get("WORKING", "#222222")
        else:
            color = c1 if s1 else c2
        parts.append(f"[{color}]{chr(code)}[/]")
    return "".join(parts)


def _gradient_color(pct: float) -> str:
    """Return a hex color interpolated across a white→yellow→orange→red ramp."""
    p = max(0.0, min(100.0, pct)) / 100.0

    if p < 0.50:
        # white -> yellow (drop blue channel)
        t = p / 0.50
        r = 0xFF
        g = 0xFF
        b = int(0xFF + (0x00 - 0xFF) * t)
    elif p < 0.80:
        # yellow -> orange (reduce green)
        t = (p - 0.50) / 0.30
        r = 0xFF
        g = int(0xFF + (0x99 - 0xFF) * t)
        b = 0x00
    else:
        # orange -> red (reduce green to zero)
        t = (p - 0.80) / 0.20
        r = 0xFF
        g = int(0x99 + (0x00 - 0x99) * t)
        b = 0x00

    return f"#{r:02x}{g:02x}{b:02x}"


def _tmux_metric_gradient_color(pct: float) -> str:
    """Return tmux metric color ramp from baseline gray to hot gradient."""
    p = max(0.0, min(100.0, pct))
    if p <= 0:
        return "#666666"

    hot = _gradient_color(p)
    hot_r = int(hot[1:3], 16)
    hot_g = int(hot[3:5], 16)
    hot_b = int(hot[5:7], 16)

    base_r, base_g, base_b = 0x66, 0x66, 0x66
    t = p / 100.0
    r = int(base_r + (hot_r - base_r) * t)
    g = int(base_g + (hot_g - base_g) * t)
    b = int(base_b + (hot_b - base_b) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _usage_gradient_color(pct: float) -> str:
    """Return the original usage-bar gradient (cyan→yellow→red)."""
    p = max(0.0, min(100.0, pct)) / 100.0
    if p < 0.70:
        t = p / 0.70
        r = int(0x00 + (0xD7 - 0x00) * t)
        g = int(0xD7 + (0xD7 - 0xD7) * t)
        b = int(0xD7 + (0x00 - 0xD7) * t)
    else:
        t = (p - 0.70) / 0.30
        r = int(0xD7 + (0xFF - 0xD7) * t)
        g = int(0xD7 + (0x33 - 0xD7) * t)
        b = int(0x00 + (0x33 - 0x00) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


class UsageBar(Static):
    """A labeled progress bar showing a percentage with smooth gradient."""

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
        tip_color = _usage_gradient_color(pct)
        bar_empty: str = "#333333"

        pct_str: str = f"{pct:.0f}%"
        pct_field: str = pct_str.rjust(4)

        extra_width: int = 7
        extra_raw: str = (self.extra_text or "")
        extra: str = extra_raw.rjust(extra_width)

        t = Text()
        t.append(f"{self.label_text} ", style="#447777")
        for i in range(filled):
            cell_pct = ((i + 1) / width) * 100
            t.append("█", style=_usage_gradient_color(cell_pct))
        t.append("░" * (width - filled), style=bar_empty)
        t.append(f"{pct_field}", style=f"bold {tip_color}")
        t.append(f" {extra}", style="#447777")
        return t
