"""Per-process metrics: CPU, RAM, GPU, I/O via /proc and nvidia-smi."""

from __future__ import annotations

import os
import subprocess
import time

from .models import ProcessMetrics

# ---------------------------------------------------------------------------
# Module-level state for delta-based metrics
# ---------------------------------------------------------------------------

_prev_proc_cpu: dict[int, tuple[float, float]] = {}
_prev_proc_io: dict[int, tuple[float, float, float]] = {}
_gpu_pmon_cache: dict[int, tuple[float, float]] | None = None
_gpu_pmon_ts: float = 0.0


def _fmt_bytes(bps: float) -> str:
    """Format bytes/sec into human-readable."""
    if bps >= 1048576:
        return f"{bps / 1048576:.1f}M"
    if bps >= 1024:
        return f"{bps / 1024:.0f}K"
    return f"{bps:.0f}B"


def _get_process_tree(root_pid: int) -> list[int]:
    """Get all PIDs in the tree rooted at root_pid (inclusive)."""
    pids: list[int] = [root_pid]
    try:
        children = subprocess.run(
            ["pgrep", "-P", str(root_pid)],
            capture_output=True, text=True, timeout=2)
        if children.returncode == 0:
            for line in children.stdout.strip().splitlines():
                try:
                    child = int(line.strip())
                    pids.extend(_get_process_tree(child))
                except ValueError:
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return pids


def _clk_tck() -> int:
    try:
        return os.sysconf("SC_CLK_TCK")
    except (ValueError, OSError):
        return 100


_CLK_TCK: int = _clk_tck()


def _read_proc_cpu(pids: list[int]) -> float:
    """Read total CPU ticks (utime+stime) for a set of PIDs."""
    total: float = 0.0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                parts = f.read().split()
            total += float(parts[13]) + float(parts[14])
        except (FileNotFoundError, IndexError, ValueError):
            pass
    return total


def _read_proc_ram(pids: list[int]) -> float:
    """Read total RSS in MB for a set of PIDs."""
    total: int = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/statm") as f:
                pages = int(f.read().split()[1])
            total += pages
        except (FileNotFoundError, IndexError, ValueError):
            pass
    page_size: int = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    return total * page_size / 1048576


def _read_gpu_pmon() -> dict[int, tuple[float, float]]:
    """Read nvidia-smi pmon, return {pid: (sm%, mem_mb)}. Cached per second."""
    global _gpu_pmon_cache, _gpu_pmon_ts
    now: float = time.time()
    if _gpu_pmon_cache is not None and now - _gpu_pmon_ts < 1.5:
        return _gpu_pmon_cache
    result: dict[int, tuple[float, float]] = {}
    try:
        r = subprocess.run(
            ["nvidia-smi", "pmon", "-c", "1", "-s", "u"],
            capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        pid = int(parts[1])
                        sm = float(parts[3]) if parts[3] != "-" else 0.0
                        result[pid] = (sm, 0.0)
                    except (ValueError, IndexError):
                        pass
        r2 = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3)
        if r2.returncode == 0:
            for line in r2.stdout.strip().splitlines():
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        pid = int(parts[0].strip())
                        mem = float(parts[1].strip())
                        sm = result.get(pid, (0.0, 0.0))[0]
                        result[pid] = (sm, mem)
                    except (ValueError, IndexError):
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    _gpu_pmon_cache = result
    _gpu_pmon_ts = now
    return result


def _has_tcp_socket(pid: int) -> bool:
    """Check if a process has at least one TCP/TCP6 socket open."""
    try:
        # Read TCP inode set once per PID
        tcp_inodes: set[str] = set()
        for proto in ("tcp", "tcp6"):
            try:
                with open(f"/proc/{pid}/net/{proto}") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 10 and parts[0] != "sl":
                            tcp_inodes.add(parts[9])
            except FileNotFoundError:
                pass
        if not tcp_inodes:
            return False
        # Check if any FD points to a TCP socket
        import os as _os
        fd_dir: str = f"/proc/{pid}/fd"
        for entry in _os.listdir(fd_dir):
            try:
                link: str = _os.readlink(f"{fd_dir}/{entry}")
                if link.startswith("socket:["):
                    inode: str = link[8:-1]
                    if inode in tcp_inodes:
                        return True
            except (OSError, ValueError):
                pass
    except (FileNotFoundError, PermissionError):
        pass
    return False


def read_process_metrics(kitty_pid: int) -> ProcessMetrics:
    """Read CPU%, RAM, GPU% for an agent's process tree."""
    global _prev_proc_cpu, _prev_proc_io
    pids: list[int] = _get_process_tree(kitty_pid)
    now: float = time.time()

    # CPU: delta-based
    ticks: float = _read_proc_cpu(pids)
    cpu_pct: float = 0.0
    prev = _prev_proc_cpu.get(kitty_pid)
    if prev is not None:
        dt: float = now - prev[1]
        if dt > 0:
            cpu_pct = ((ticks - prev[0]) / _CLK_TCK / dt) * 100
    _prev_proc_cpu[kitty_pid] = (ticks, now)

    # RAM
    ram_mb: float = _read_proc_ram(pids)

    # GPU: match any PID in tree
    gpu_data: dict[int, tuple[float, float]] = _read_gpu_pmon()
    gpu_pct: float = 0.0
    gpu_mem: float = 0.0
    pid_set: set[int] = set(pids)
    for pid, (sm, mem) in gpu_data.items():
        if pid in pid_set:
            gpu_pct += sm
            gpu_mem += mem

    # Network I/O: delta-based from /proc/<pid>/io
    # Only count PIDs that have at least one TCP socket open,
    # to exclude pipe/internal I/O from bash, tee, npm, etc.
    # net_read ≈ rchar - read_bytes (total reads minus disk reads)
    # net_write ≈ wchar - write_bytes (total writes minus disk writes)
    net_rchar: float = 0.0
    net_wchar: float = 0.0
    for pid in pids:
        if not _has_tcp_socket(pid):
            continue
        try:
            rchar: float = 0.0
            wchar: float = 0.0
            read_bytes: float = 0.0
            write_bytes: float = 0.0
            with open(f"/proc/{pid}/io") as f:
                for line in f:
                    if line.startswith("rchar:"):
                        rchar = float(line.split()[1])
                    elif line.startswith("wchar:"):
                        wchar = float(line.split()[1])
                    elif line.startswith("read_bytes:"):
                        read_bytes = float(line.split()[1])
                    elif line.startswith("write_bytes:"):
                        write_bytes = float(line.split()[1])
            net_rchar += max(0, rchar - read_bytes)
            net_wchar += max(0, wchar - write_bytes)
        except (FileNotFoundError, PermissionError, IndexError, ValueError):
            pass
    io_read: float = 0.0
    io_write: float = 0.0
    prev_io = _prev_proc_io.get(kitty_pid)
    if prev_io is not None:
        dt = now - prev_io[2]
        if dt > 0:
            io_read = max(0, (net_rchar - prev_io[0]) / dt)
            io_write = max(0, (net_wchar - prev_io[1]) / dt)
    _prev_proc_io[kitty_pid] = (net_rchar, net_wchar, now)

    return ProcessMetrics(
        cpu_pct=cpu_pct, ram_mb=ram_mb,
        gpu_pct=gpu_pct, gpu_mem_mb=gpu_mem,
        io_read_bps=io_read, io_write_bps=io_write,
    )
