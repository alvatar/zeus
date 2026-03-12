"""Low-level Textual driver hooks for optional dashboard input tracing."""

from __future__ import annotations

from codecs import getincrementaldecoder
import os
import selectors

from textual import events
from textual._loop import loop_last
from textual._parser import ParseError
from textual._xterm_parser import XTermParser
from textual.drivers.linux_driver import LinuxDriver
from textual.message import Message

from .input_trace import (
    input_trace_bytes_hex,
    input_trace_bytes_repr,
    input_trace_enabled,
    input_trace_preview,
    input_trace_repr,
    write_input_trace_record,
)


def _message_trace_fields(message: Message) -> dict[str, object]:
    fields: dict[str, object] = {
        "message_type": type(message).__name__,
        "message_repr": input_trace_repr(message),
    }

    if isinstance(message, events.Key):
        fields.update(
            key=getattr(message, "key", None),
            character=getattr(message, "character", None),
            printable=getattr(message, "is_printable", False),
        )
    elif isinstance(message, events.Paste):
        text = getattr(message, "text", "") or ""
        fields.update(
            text_len=len(text),
            text_preview=input_trace_preview(text),
        )
    elif isinstance(message, events.Resize):
        size = getattr(message, "size", None)
        pixel_size = getattr(message, "pixel_size", None)
        if size is not None:
            fields.update(width=size.width, height=size.height)
        if pixel_size is not None:
            fields.update(pixel_width=pixel_size.width, pixel_height=pixel_size.height)
    elif isinstance(message, events.MouseEvent):
        fields.update(
            x=getattr(message, "x", None),
            y=getattr(message, "y", None),
            button=getattr(message, "button", None),
        )

    return fields


class TracingLinuxDriver(LinuxDriver):
    """Linux driver variant that traces raw terminal input below ``on_key``."""

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._trace_seq = 0

    def _trace_input(self, kind: str, **fields: object) -> None:
        if not input_trace_enabled():
            return
        self._trace_seq += 1
        write_input_trace_record(
            kind,
            driver_class=type(self).__name__,
            driver_seq=self._trace_seq,
            **fields,
        )

    def send_message(self, message: Message) -> None:
        self._trace_input("driver.dispatch", **_message_trace_fields(message))
        super().send_message(message)

    def run_input_thread(self) -> None:
        """Wait for raw terminal input and dispatch traced events."""
        selector = selectors.SelectSelector()
        selector.register(self.fileno, selectors.EVENT_READ)

        fileno = self.fileno
        event_read = selectors.EVENT_READ

        parser = XTermParser(self._debug)
        feed = parser.feed
        tick = parser.tick

        utf8_decoder = getincrementaldecoder("utf-8")().decode
        decode = utf8_decoder
        read = os.read

        self._trace_input(
            "driver.thread.start",
            fileno=fileno,
            input_tty=self.input_tty,
        )

        def process_selector_events(
            selector_events: list[tuple[selectors.SelectorKey, int]],
            final: bool = False,
        ) -> None:
            for last, (_selector_key, mask) in loop_last(selector_events):
                if not mask & event_read:
                    continue

                final_read = final and last
                raw = read(fileno, 1024 * 4)
                self._trace_input(
                    "driver.read",
                    final=final_read,
                    raw_len=len(raw),
                    raw_hex=input_trace_bytes_hex(raw),
                    raw_preview=input_trace_bytes_repr(raw),
                )

                try:
                    unicode_data = decode(raw, final=final_read)
                except UnicodeDecodeError as exc:
                    self._trace_input(
                        "driver.decode.error",
                        final=final_read,
                        error=input_trace_repr(exc),
                        raw_len=len(raw),
                        raw_hex=input_trace_bytes_hex(raw),
                    )
                    raise

                self._trace_input(
                    "driver.decode",
                    final=final_read,
                    raw_len=len(raw),
                    text_len=len(unicode_data),
                    text_preview=input_trace_repr(unicode_data),
                )

                if not unicode_data:
                    break

                try:
                    for event in feed(unicode_data):
                        self._trace_input(
                            "driver.parsed",
                            source="feed",
                            **_message_trace_fields(event),
                        )
                        self.process_message(event)
                except ParseError as exc:
                    self._trace_input(
                        "driver.parse.error",
                        source="feed",
                        error=input_trace_repr(exc),
                        text_preview=input_trace_repr(unicode_data),
                    )
                    raise

            try:
                for event in tick():
                    self._trace_input(
                        "driver.parsed",
                        source="tick",
                        **_message_trace_fields(event),
                    )
                    self.process_message(event)
            except ParseError as exc:
                self._trace_input(
                    "driver.parse.error",
                    source="tick",
                    error=input_trace_repr(exc),
                )
                raise

        try:
            while not self.exit_event.is_set():
                process_selector_events(selector.select(0.1))
            selector.unregister(self.fileno)
            process_selector_events(selector.select(0.1), final=True)
        finally:
            selector.close()
            try:
                for _event in feed(""):
                    pass
            except (EOFError, ParseError):
                pass
            self._trace_input("driver.thread.stop")
