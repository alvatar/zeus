"""Tests for CPU/GPU column color behavior in dashboard rows."""

import inspect

from zeus.dashboard.app import ZeusApp


def test_cpu_gpu_columns_use_gradient_except_zero_percent() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert "if cpu_pct <= 0:" in source
    assert "if gpu_pct <= 0:" in source
    assert "style=_gradient_color(cpu_pct)" in source
    assert "style=_gradient_color(gpu_pct)" in source
