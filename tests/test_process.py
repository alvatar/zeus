"""Tests for process metrics helpers."""

import zeus.process as process
from zeus.models import ProcessMetrics
from zeus.process import fmt_bytes


def test_fmt_bytes_small():
    assert fmt_bytes(0) == "0B"
    assert fmt_bytes(500) == "500B"
    assert fmt_bytes(1023) == "1023B"


def test_fmt_bytes_kb():
    assert fmt_bytes(1024) == "1K"
    assert fmt_bytes(2048) == "2K"
    assert fmt_bytes(50000) == "49K"


def test_fmt_bytes_mb():
    assert fmt_bytes(1048576) == "1.0M"
    assert fmt_bytes(5 * 1048576) == "5.0M"
    assert fmt_bytes(1_500_000) == "1.4M"


def test_get_process_tree_reads_proc_children_iteratively(monkeypatch) -> None:
    children = {
        10: [11, 12],
        11: [13],
        12: [],
        13: [],
    }

    monkeypatch.setattr(process.os.path, "exists", lambda path: path == "/proc/10")
    monkeypatch.setattr(process, "_read_proc_children", lambda pid: children.get(pid, []))

    tree = process._get_process_tree(10)

    assert tree[0] == 10
    assert set(tree) == {10, 11, 12, 13}


def test_read_process_metrics_resets_cpu_delta_on_root_identity_change(
    monkeypatch,
) -> None:
    monkeypatch.setattr(process, "_prev_proc_cpu", {42: (100.0, 1.0, 10)})
    monkeypatch.setattr(process, "_prev_proc_io", {})

    monkeypatch.setattr(process, "_get_process_tree", lambda pid: [42])
    monkeypatch.setattr(process, "_read_proc_stat_fields", lambda pid: (1, 0, 0, 11))
    monkeypatch.setattr(process, "_read_proc_cpu", lambda pids: 140.0)
    monkeypatch.setattr(process, "_read_proc_ram", lambda pids: 256.0)
    monkeypatch.setattr(process, "_read_gpu_pmon", lambda: {})
    monkeypatch.setattr(process, "_net_io_tcp_diag", lambda pids: None)
    monkeypatch.setattr(process.time, "time", lambda: 2.0)

    metrics = process.read_process_metrics(42)

    assert metrics.cpu_pct == 0.0
    assert metrics.ram_mb == 256.0
    assert process._prev_proc_cpu[42] == (140.0, 2.0, 11)


def test_read_process_metrics_clears_cache_when_root_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(process, "_prev_proc_cpu", {42: (100.0, 1.0, 10)})
    monkeypatch.setattr(process, "_prev_proc_io", {42: (1.0, 2.0, 3.0, 10)})
    monkeypatch.setattr(process, "_get_process_tree", lambda pid: [])

    metrics = process.read_process_metrics(42)

    assert metrics == ProcessMetrics()
    assert process._prev_proc_cpu == {}
    assert process._prev_proc_io == {}
