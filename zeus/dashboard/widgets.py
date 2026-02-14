"""Custom widgets: ZeusDataTable, UsageBar, ZeusTextArea, SplashOverlay."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import time
from typing import TYPE_CHECKING, ClassVar, cast

from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Static, TextArea
from rich.text import Text

if TYPE_CHECKING:
    from textual.timer import Timer


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


# ── Braille sparkline ─────────────────────────────────────────────────

_BRAILLE_BASE = 0x2800
# Cumulative dot patterns for left/right columns, heights 0-4 (bottom up)
_LEFT_FILL = (0x00, 0x40, 0x44, 0x46, 0x47)
_RIGHT_FILL = (0x00, 0x80, 0xA0, 0xB0, 0xB8)


def braille_sparkline(
    values: list[float],
    width: int = 25,
) -> Text:
    """Render values (0–100) as a colored braille sparkline.

    Each braille character encodes two adjacent data points with
    4 vertical height levels.  Color per character follows the
    cyan→yellow→red gradient based on the pair's average value.
    """
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


# State → (color, braille height 0–3)
_STATE_SPARK: dict[str, tuple[str, int]] = {
    "WORKING": ("#00ff00", 3),
    "WAITING": ("#ffdd00", 2),
    "IDLE":    ("#ff4444", 1),
}

# Lifted fill tables — skip bottom row (row 3), use rows 2,1,0 only
_LEFT_FILL_UP = (0x00, 0x04, 0x06, 0x07)
_RIGHT_FILL_UP = (0x00, 0x20, 0x30, 0x38)


def state_sparkline_markup(
    states: list[str],
    width: int = 25,
) -> str:
    """Render state labels as a colored braille sparkline.

    WORKING = tall green, WAITING = mid yellow, IDLE = short red.
    Empty (no data) = blank.
    """
    n = width * 2
    # Always use even number of real samples so pairings stay stable
    real = list(states[-n:]) if len(states) >= n else list(states)
    if len(real) % 2 == 1:
        real = real[1:]  # drop oldest
    pad = n - len(real)
    vals = [""] * pad + real

    parts: list[str] = []
    for i in range(0, len(vals), 2):
        s1, s2 = vals[i], vals[i + 1]
        c1, h1 = _STATE_SPARK.get(s1, ("#222222", 0))
        c2, h2 = _STATE_SPARK.get(s2, ("#222222", 0))
        code = _BRAILLE_BASE | _LEFT_FILL_UP[h1] | _RIGHT_FILL_UP[h2]
        # Use the more urgent state's color for the character
        # Priority: WAITING > WORKING > IDLE > empty
        if s1 == s2:
            color = c1
        elif "WAITING" in (s1, s2):
            color = "#ffdd00"
        elif "WORKING" in (s1, s2):
            color = "#00ff00"
        else:
            color = c1 if s1 else c2
        parts.append(f"[{color}]{chr(code)}[/]")
    return "".join(parts)


def _gradient_color(pct: float) -> str:
    """Return a hex color smoothly interpolated across a cyan→yellow→red ramp."""
    p = max(0.0, min(100.0, pct)) / 100.0
    # Ramp: 0%=#00d7d7 (cyan) → 70%=#d7d700 (yellow) → 100%=#ff3333 (red)
    if p < 0.70:
        t = p / 0.70
        r = int(0x00 + (0xd7 - 0x00) * t)
        g = int(0xd7 + (0xd7 - 0xd7) * t)
        b = int(0xd7 + (0x00 - 0xd7) * t)
    else:
        t = (p - 0.70) / 0.30
        r = int(0xd7 + (0xff - 0xd7) * t)
        g = int(0xd7 + (0x33 - 0xd7) * t)
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
        tip_color = _gradient_color(pct)
        bar_empty: str = "#333333"

        pct_str: str = f"{pct:.0f}%"
        pct_field: str = pct_str.rjust(4)

        extra_width: int = 7
        extra: str = (self.extra_text or "").ljust(extra_width)

        t = Text()
        t.append(f"{self.label_text} ", style="#447777")
        # Per-cell gradient: each filled block gets the color for its position
        for i in range(filled):
            cell_pct = ((i + 1) / width) * 100
            t.append("█", style=_gradient_color(cell_pct))
        t.append("░" * (width - filled), style=bar_empty)
        t.append(f"{pct_field}", style=f"bold {tip_color}")
        t.append(f" {extra}", style="#447777")
        return t


# ── Splash overlay ────────────────────────────────────────────────────

_SPLASH_ART: list[str] = [
    "[bold #00d7d7]            ██                   [/]",
    "[bold #00d7d7]           ██                    [/]",
    "[bold #00d7d7]          ████████               [/]",
    "[bold #00d7d7]            ███                  [/]",
    "[bold #00d7d7]           ██                    [/]",
    "[bold #00d7d7]          ██                     [/]",
    "                                 ",
    "[#1a3a3a]╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸[/]",
    "[#00d7d7]███████╗███████╗██╗   ██╗███████╗[/]",
    "[#00b5b5]╚══███╔╝██╔════╝██║   ██║██╔════╝[/]",
    "[#009999]  ███╔╝ █████╗  ██║   ██║███████╗[/]",
    "[#00b5b5] ███╔╝  ██╔══╝  ██║   ██║╚════██║[/]",
    "[#00d7d7]███████╗███████╗╚██████╔╝███████║[/]",
    "[#00e8e8]╚══════╝╚══════╝ ╚═════╝ ╚══════╝[/]",
    "[#1a3a3a]╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸[/]",
    "",
    "[#3a6a6a]     Agent Fleet Commander[/]",
]


class SplashOverlay(Static):
    """Animated startup splash with typewriter reveal and fade-out."""

    DEFAULT_CSS = """
    SplashOverlay {
        layer: splash;
        width: 100%;
        height: 100%;
        background: #000000;
        content-align: center middle;
        overflow: hidden hidden;
        scrollbar-size: 0 0;
    }
    """

    _reveal: int = 0
    _tick_timer: Timer | None = None

    def on_mount(self) -> None:
        self._reveal = 0
        self._tick_timer = self.set_interval(0.09, self._tick)

    def _tick(self) -> None:
        if self._reveal < len(_SPLASH_ART):
            self._reveal += 1
            self.update("\n".join(_SPLASH_ART[: self._reveal]))
        else:
            if self._tick_timer:
                self._tick_timer.stop()
                self._tick_timer = None
            self.set_timer(0.8, self._fade_out)

    def _fade_out(self) -> None:
        self.styles.animate(
            "opacity", 0.0, duration=0.5, easing="out_cubic",
        )
        self.set_timer(0.55, self._do_remove)

    def _do_remove(self) -> None:
        try:
            self.remove()
        except Exception:
            pass

    def dismiss(self) -> None:
        """Immediately skip and remove the splash."""
        if self._tick_timer:
            self._tick_timer.stop()
            self._tick_timer = None
        try:
            self.remove()
        except Exception:
            pass
