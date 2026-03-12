"""Tests for optional dashboard input trace logging."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.widgets_text import ZeusTextArea


class _DummyInteractInput:
    def __init__(self, text: str = "") -> None:
        self.id = "interact-input"
        self.text = text
        self.styles = SimpleNamespace(height=3)
        self.size = SimpleNamespace(width=80)

    def clear(self) -> None:
        self.text = ""


class _DummyKeyEvent:
    def __init__(self, key: str, *, character: str | None = None, printable: bool = True) -> None:
        self.key = key
        self.character = character
        self.is_printable = printable
        self.prevented = False
        self.stopped = False

    def prevent_default(self) -> None:
        self.prevented = True

    def stop(self) -> None:
        self.stopped = True


def _read_trace(path) -> list[dict[str, object]]:  # noqa: ANN001
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_input_trace_logs_text_area_changes(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"
    input_widget = _DummyInteractInput("hello")

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))
    app._interact_agent_key = "agent-key"
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: input_widget)

    app.on_text_area_changed(SimpleNamespace(text_area=input_widget))

    records = _read_trace(trace_path)
    assert any(
        record["kind"] == "text_area_changed"
        and record["text_preview"] == "hello"
        and record["interact_target_key"] == "agent:agent-key"
        for record in records
    )


def test_input_trace_logs_run_action(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))
    monkeypatch.setattr(app, "poll_and_update", lambda: None)

    asyncio.run(app.run_action("refresh"))

    records = _read_trace(trace_path)
    kinds = [record["kind"] for record in records]
    assert "run_action.before" in kinds
    assert "run_action.after" in kinds
    assert any(record.get("action") == "refresh" for record in records)


def test_input_trace_logs_key_events(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))

    app.on_key(_DummyKeyEvent("x", character="x", printable=True))

    records = _read_trace(trace_path)
    assert any(
        record["kind"] == "key"
        and record["phase"] == "start"
        and record["key"] == "x"
        for record in records
    )
    assert any(
        record["kind"] == "key"
        and record["phase"] == "pass"
        and record["key"] == "x"
        for record in records
    )


def test_input_trace_logs_row_selection_events(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"
    timer = SimpleNamespace(stop=lambda: None)

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))
    monkeypatch.setattr(app, "set_timer", lambda _delay, _fn: timer)

    app.on_data_table_row_highlighted(
        SimpleNamespace(row_key=SimpleNamespace(value="row-7"), cursor_row=7)
    )

    records = _read_trace(trace_path)
    assert any(
        record["kind"] == "row_highlighted"
        and record["row_key"] == "row-7"
        and record["cursor_row"] == 7
        for record in records
    )


def test_input_trace_logs_modal_text_area_changes(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"
    input_widget = _DummyInteractInput("draft body")
    input_widget.id = "agent-message-input"

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))

    app.on_text_area_changed(SimpleNamespace(text_area=input_widget))

    records = _read_trace(trace_path)
    assert any(
        record["kind"] == "text_area_changed"
        and record["text_area_id"] == "agent-message-input"
        and record["text_preview"] == "draft body"
        for record in records
    )


def test_input_trace_logs_zeus_text_area_key_events(monkeypatch, tmp_path) -> None:
    app = ZeusApp()
    trace_path = tmp_path / "input-trace.jsonl"

    class _TraceTextArea(ZeusTextArea):
        def __init__(self, trace_app: ZeusApp) -> None:
            super().__init__("", id="agent-message-input")
            self._trace_app = trace_app

        @property
        def app(self):  # noqa: ANN201
            return self._trace_app

    monkeypatch.setenv("ZEUS_INPUT_TRACE", "1")
    monkeypatch.setenv("ZEUS_INPUT_TRACE_FILE", str(trace_path))

    ta = _TraceTextArea(app)
    ta.on_key(_DummyKeyEvent("x", character="x", printable=True))

    records = _read_trace(trace_path)
    assert any(
        record["kind"] == "textarea.key"
        and record["widget_id"] == "agent-message-input"
        and record["key"] == "x"
        for record in records
    )
