"""Tests for CPU/GPU column color behavior in dashboard rows."""

import inspect

from zeus.dashboard.app import ZeusApp


def test_cpu_gpu_columns_do_not_use_gradient_style_in_rows() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert 'style=_gradient_color(pm.cpu_pct)' not in source
    assert 'style=_gradient_color(pm.gpu_pct)' not in source
