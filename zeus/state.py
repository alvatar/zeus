"""State detection and footer parsing from agent screen text."""

from __future__ import annotations

import re

from .config import SPINNER_RE, MODEL_RE, CTX_RE, TOKENS_RE
from .models import State

_WORKING_WORD_RE = re.compile(r"\bWORKING\b", re.IGNORECASE)


def detect_state(screen: str) -> State:
    """Detect coarse state from raw screen text.

    WORKING when:
    - spinner is present, or
    - trailing status lines explicitly say WORKING.
    """
    if SPINNER_RE.search(screen):
        return State.WORKING

    # Pi often shows explicit WORKING in the bottom status area.
    tail = [line.strip() for line in screen.splitlines() if line.strip()][-6:]
    if any(_WORKING_WORD_RE.search(line) for line in tail):
        return State.WORKING

    return State.IDLE


def activity_signature(screen: str) -> str:
    """Return a normalized signature for activity/change detection.

    Strips empty lines and footer usage line; keeps only recent meaningful lines.
    """
    lines: list[str] = []
    for raw in screen.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # Footer line with model/ctx/tokens is noisy for churn detection.
        if CTX_RE.search(line):
            continue
        lines.append(line.strip())

    # Keep recent content only.
    if len(lines) > 80:
        lines = lines[-80:]
    return "\n".join(lines)


def parse_footer(screen: str) -> tuple[str, float, str, str]:
    """Parse model, context %, and token counts from the screen footer.

    Returns (model, ctx_pct, tokens_in, tokens_out).
    """
    model: str = ""
    ctx_pct: float = 0.0
    tokens_in: str = ""
    tokens_out: str = ""
    for line in reversed(screen.splitlines()):
        stripped: str = line.strip()
        if not stripped:
            continue
        ctx_match = CTX_RE.search(stripped)
        if ctx_match:
            ctx_pct = float(ctx_match.group(1))
            model_match = MODEL_RE.match(stripped)
            if model_match:
                m: str = model_match.group(1)
                thinking: str = model_match.group(2) or ""
                m = re.sub(
                    r"-2025\d{4}|-2026\d{4}", "", m
                ).replace("claude-", "")
                model = f"{m} ({thinking})" if thinking else m
            tok_match = TOKENS_RE.search(stripped)
            if tok_match:
                tokens_in = tok_match.group(1)
                tokens_out = tok_match.group(2)
            break
    return model, ctx_pct, tokens_in, tokens_out
