"""Usage API facade and shared time helpers."""

from __future__ import annotations

import re

from .models import UsageData, OpenAIUsageData
from .usage_claude import fetch_claude_usage, read_usage
from .usage_openai import fetch_openai_usage, read_openai_usage


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _fmt_countdown(secs: int) -> str:
    if secs <= 0:
        return "now"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d > 0:
        return f"{d}d{h:02d}h"
    if h > 0:
        return f"{h}h{m:02d}m"
    if m > 0:
        return f"{m}m"
    return f"{s}s"


def time_left(value: str) -> str:
    """Convert a reset timestamp or duration to a human-readable countdown."""
    if not value:
        return ""
    raw: str = value.strip()

    duration = re.match(r"^(\d+(?:\.\d+)?)(ms|s|m|h)?$", raw)
    if duration and "T" not in raw:
        amount: float = float(duration.group(1))
        unit: str = duration.group(2) or "s"
        if unit == "ms":
            secs = int(round(amount / 1000))
        elif unit == "m":
            secs = int(round(amount * 60))
        elif unit == "h":
            secs = int(round(amount * 3600))
        else:
            secs = int(round(amount))
        return _fmt_countdown(secs)

    try:
        from datetime import datetime, timezone

        resets = datetime.fromisoformat(raw)
        now = datetime.now(timezone.utc)
        delta = resets - now
        secs = int(delta.total_seconds())
        return _fmt_countdown(secs)
    except (ValueError, TypeError, OverflowError):
        return ""


# Backward-compatible alias for older imports.
_time_left = time_left


__all__ = [
    "UsageData",
    "OpenAIUsageData",
    "fetch_claude_usage",
    "fetch_openai_usage",
    "read_openai_usage",
    "read_usage",
    "time_left",
]
