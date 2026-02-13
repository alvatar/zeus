"""Interact stream parsing and ANSI normalization helpers."""

from __future__ import annotations

import re

_SGR_RE = re.compile(r"\x1b\[([0-9:;]*)m")
_ANSI_RE = re.compile(r"\x1b\[[0-9;:]*[A-Za-z]")


def kitty_ansi_to_standard(text: str) -> str:
    """Convert kitty's colon-separated SGR params to semicolons for Rich."""
    return _SGR_RE.sub(
        lambda m: f"\x1b[{m.group(1).replace(':', ';')}m",
        text,
    )


def trim_trailing_blank_lines(text: str) -> str:
    """Drop trailing blank lines while preserving line endings."""
    lines = text.splitlines(keepends=True)
    while lines and not lines[-1].strip():
        lines.pop()
    return "".join(lines)


def _is_separator_line(plain: str, min_len: int = 20) -> bool:
    return len(plain) >= min_len and all(c == "─" for c in plain)


def strip_pi_input_chrome(screen_text: str, min_sep_len: int = 20) -> str:
    """Strip pi input/status chrome by cutting at 2nd separator from bottom."""
    lines = screen_text.splitlines(keepends=True)
    sep_count = 0
    cut_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        plain = _ANSI_RE.sub("", lines[i]).strip()
        if _is_separator_line(plain, min_len=min_sep_len):
            sep_count += 1
            if sep_count == 2:
                cut_at = i
                break
    return "".join(lines[:cut_at])
