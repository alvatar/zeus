"""Shared helpers for optional dashboard input tracing."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import threading
import time

_INPUT_TRACE_ENV_TRUE = {"1", "true", "yes", "on"}
_INPUT_TRACE_PREVIEW_MAX = 160
_INPUT_TRACE_BYTES_PREVIEW_MAX = 96
_INPUT_TRACE_LOCK = threading.Lock()


def input_trace_enabled() -> bool:
    """Return whether input tracing is enabled via environment."""
    raw = (os.environ.get("ZEUS_INPUT_TRACE") or "").strip().lower()
    return raw in _INPUT_TRACE_ENV_TRUE


def input_trace_path() -> str:
    """Return the current input trace file path."""
    configured = (os.environ.get("ZEUS_INPUT_TRACE_FILE") or "").strip()
    if configured:
        return os.path.expanduser(configured)
    return f"/tmp/zeus-input-trace-{os.getpid()}.jsonl"


def input_trace_preview(text: str, max_len: int = _INPUT_TRACE_PREVIEW_MAX) -> str:
    """Return a stable abbreviated preview for trace fields."""
    if len(text) <= max_len:
        return text
    head = max_len // 2
    tail = max_len - head - 1
    return f"{text[:head]}…{text[-tail:]}"


def input_trace_repr(value: object, max_len: int = _INPUT_TRACE_PREVIEW_MAX) -> str:
    """Return a repr-based preview suitable for JSON trace output."""
    return input_trace_preview(repr(value), max_len=max_len)


def input_trace_bytes_hex(data: bytes, max_bytes: int = _INPUT_TRACE_BYTES_PREVIEW_MAX) -> str:
    """Return a compact hex preview for raw input bytes."""
    if len(data) <= max_bytes:
        return data.hex()
    head = max_bytes // 2
    tail = max_bytes - head
    return f"{data[:head].hex()}…{data[-tail:].hex()}"


def input_trace_bytes_repr(data: bytes, max_len: int = _INPUT_TRACE_PREVIEW_MAX) -> str:
    """Return a repr-based preview for raw input bytes."""
    return input_trace_repr(data, max_len=max_len)


def write_input_trace_record(
    kind: str,
    *,
    state: Mapping[str, object] | None = None,
    **fields: object,
) -> None:
    """Append a trace record when input tracing is enabled."""
    if not input_trace_enabled():
        return

    record: dict[str, object] = {
        "ts": time.time(),
        "kind": kind,
        "thread": threading.current_thread().name,
    }
    if state is not None:
        record.update(state)
    record.update(fields)

    try:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        safe_fields = {key: input_trace_repr(value) for key, value in record.items()}
        line = json.dumps(safe_fields, ensure_ascii=False, sort_keys=True)

    try:
        with _INPUT_TRACE_LOCK:
            with open(input_trace_path(), "a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
    except OSError:
        pass
