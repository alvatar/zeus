"""Compatibility exports for dashboard widget modules."""

from . import widgets_text as _widgets_text
from .widgets_overlays import DopamineOverlay, SplashOverlay, SteadyLadOverlay
from .widgets_text import ZeusDataTable, ZeusTextArea
from .widgets_visual import (
    UsageBar,
    _gradient_color,
    braille_sparkline,
    braille_sparkline_markup,
    state_sparkline_markup,
)

# Backward-compatible module aliases used by tests and monkeypatching.
subprocess = _widgets_text.subprocess
shutil = _widgets_text.shutil
tempfile = _widgets_text.tempfile

__all__ = [
    "DopamineOverlay",
    "SplashOverlay",
    "SteadyLadOverlay",
    "UsageBar",
    "ZeusDataTable",
    "ZeusTextArea",
    "_gradient_color",
    "braille_sparkline",
    "braille_sparkline_markup",
    "shutil",
    "state_sparkline_markup",
    "subprocess",
    "tempfile",
]
