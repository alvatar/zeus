"""State detection and footer parsing from agent screen text."""

import re

from .config import SPINNER_RE, MODEL_RE, CTX_RE, TOKENS_RE
from .models import State


def detect_state(screen: str) -> State:
    if SPINNER_RE.search(screen):
        return State.WORKING
    return State.IDLE


def parse_footer(screen: str) -> tuple[str, float, str, str]:
    """Parse model, context %, and token counts from the screen footer.

    Returns (model, ctx_pct, tokens_in, tokens_out).
    """
    model, ctx_pct, tokens_in, tokens_out = "", 0.0, "", ""
    for line in reversed(screen.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        ctx_match = CTX_RE.search(stripped)
        if ctx_match:
            ctx_pct = float(ctx_match.group(1))
            model_match = MODEL_RE.match(stripped)
            if model_match:
                m = model_match.group(1)
                thinking = model_match.group(2) or ""
                m = re.sub(r"-2025\d{4}|-2026\d{4}", "", m).replace("claude-", "")
                model = f"{m} ({thinking})" if thinking else m
            tok_match = TOKENS_RE.search(stripped)
            if tok_match:
                tokens_in = tok_match.group(1)
                tokens_out = tok_match.group(2)
            break
    return model, ctx_pct, tokens_in, tokens_out
