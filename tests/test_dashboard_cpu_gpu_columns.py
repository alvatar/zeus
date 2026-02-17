"""Tests for CPU/GPU column color behavior in dashboard rows."""

import inspect
from pathlib import Path

from zeus.dashboard.app import ZeusApp


def test_cpu_gpu_columns_use_gradient_except_zero_percent() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert "if cpu_pct <= 0:" in source
    assert "if gpu_pct <= 0:" in source
    assert "style=_gradient_color(cpu_pct)" in source
    assert "style=_gradient_color(gpu_pct)" in source


def test_tmux_cpu_gpu_columns_use_tmux_gradient_from_gray_baseline() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert "style=_tmux_metric_gradient_color(cpu_pct)" in source
    assert "style=_tmux_metric_gradient_color(gpu_pct)" in source


def test_detached_tmux_rows_do_not_overwrite_cpu_gpu_heat_colors() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert "cpu_t = Text(str(cpu_t), style=dim)" not in source
    assert "gpu_t = Text(str(gpu_t), style=dim)" not in source
    assert "if isinstance(cpu_t, str):" in source
    assert "if isinstance(gpu_t, str):" in source


def test_default_config_sets_cpu_column_one_char_wider() -> None:
    text = (Path(__file__).resolve().parents[1] / "zeus" / "default_config.toml").read_text()

    assert "[columns.split.widths]" in text
    assert "[columns.wide.widths]" in text
    assert text.count("CPU = 5") >= 2
