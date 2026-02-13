"""Per-process metrics: CPU, RAM, GPU, I/O via /proc and nvidia-smi."""

from __future__ import annotations

import os
import socket
import struct
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

# tcp_diag availability: None = untested, True/False = cached result
_tcp_diag_available: bool | None = None

# ---------------------------------------------------------------------------
# Netlink SOCK_DIAG constants
# ---------------------------------------------------------------------------
_NETLINK_SOCK_DIAG: int = 4
_SOCK_DIAG_BY_FAMILY: int = 20
_NLMSG_DONE: int = 3
_NLMSG_ERROR: int = 2
_NLM_F_REQUEST: int = 0x01
_NLM_F_DUMP: int = 0x300
_INET_DIAG_INFO: int = 2  # nlattr type for TCP_INFO

# tcp_info struct offsets (x86-64, Linux ≥ 4.2):
# After 8×u8 + 23×u32 + 4-byte padding = offset 104
#   104: tcpi_pacing_rate     (u64)
#   112: tcpi_max_pacing_rate (u64)
#   120: tcpi_bytes_acked     (u64)  ≈ bytes sent
#   128: tcpi_bytes_received  (u64)
_TCPI_BYTES_ACKED_OFF: int = 120
_TCPI_BYTES_RECEIVED_OFF: int = 128
_TCPI_MIN_LEN: int = 136  # need at least this many bytes


def fmt_bytes(bps: float) -> str:
    """Format bytes/sec into human-readable."""
    if bps >= 1048576:
        return f"{bps / 1048576:.1f}M"
    if bps >= 1024:
        return f"{bps / 1024:.0f}K"
    return f"{bps:.0f}B"


# Backward-compatible alias for older imports.
_fmt_bytes = fmt_bytes


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


def _get_socket_inodes(pids: list[int]) -> set[int]:
    """Collect socket inodes owned by any PID in the list."""
    inodes: set[int] = set()
    for pid in pids:
        fd_dir: str = f"/proc/{pid}/fd"
        try:
            for entry in os.listdir(fd_dir):
                try:
                    link: str = os.readlink(f"{fd_dir}/{entry}")
                    if link.startswith("socket:["):
                        inodes.add(int(link[8:-1]))
                except (OSError, ValueError):
                    pass
        except (FileNotFoundError, PermissionError):
            pass
    return inodes


def _has_tcp_socket(pid: int) -> bool:
    """Check if a process has at least one TCP/TCP6 socket open."""
    try:
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
        fd_dir: str = f"/proc/{pid}/fd"
        for entry in os.listdir(fd_dir):
            try:
                link: str = os.readlink(f"{fd_dir}/{entry}")
                if link.startswith("socket:["):
                    if link[8:-1] in tcp_inodes:
                        return True
            except (OSError, ValueError):
                pass
    except (FileNotFoundError, PermissionError):
        pass
    return False


def _query_tcp_bytes() -> dict[int, tuple[int, int]]:
    """Query per-socket TCP byte counters via NETLINK_SOCK_DIAG.

    Returns ``{inode: (bytes_received, bytes_acked)}``.
    Requires the ``tcp_diag`` kernel module.  Returns empty dict on failure.
    """
    global _tcp_diag_available
    if _tcp_diag_available is False:
        return {}

    results: dict[int, tuple[int, int]] = {}
    try:
        sock = socket.socket(
            socket.AF_NETLINK, socket.SOCK_DGRAM, _NETLINK_SOCK_DIAG)
        sock.settimeout(1.0)
        sock.bind((0, 0))
    except OSError:
        _tcp_diag_available = False
        return {}

    try:
        for family in (socket.AF_INET, socket.AF_INET6):
            idiag_ext: int = 1 << (_INET_DIAG_INFO - 1)
            sockid: bytes = b"\x00" * 48
            payload: bytes = struct.pack(
                "=BBBBI", family, socket.IPPROTO_TCP,
                idiag_ext, 0, 0xFFFFFFFF,
            ) + sockid
            nlh: bytes = struct.pack(
                "=IHHII",
                16 + len(payload),
                _SOCK_DIAG_BY_FAMILY,
                _NLM_F_REQUEST | _NLM_F_DUMP,
                0, 0,
            )
            sock.send(nlh + payload)

            done: bool = False
            while not done:
                try:
                    data: bytes = sock.recv(65536)
                except socket.timeout:
                    break
                off: int = 0
                while off < len(data):
                    if off + 16 > len(data):
                        break
                    nl_len, nl_type = struct.unpack_from("=IH", data, off)
                    if nl_type == _NLMSG_DONE:
                        done = True
                        break
                    if nl_type == _NLMSG_ERROR:
                        # tcp_diag not available
                        _tcp_diag_available = False
                        sock.close()
                        return {}
                    if nl_len < 16:
                        break
                    # inet_diag_msg is 72 bytes after the 16-byte nlh
                    msg_off: int = off + 16
                    if msg_off + 72 <= off + nl_len:
                        inode: int = struct.unpack_from(
                            "=I", data, msg_off + 68)[0]
                        # Walk nlattrs after inet_diag_msg
                        attr_off: int = msg_off + 72
                        while attr_off + 4 <= off + nl_len:
                            al, at = struct.unpack_from(
                                "=HH", data, attr_off)
                            if al < 4:
                                break
                            if (at == _INET_DIAG_INFO
                                    and al - 4 >= _TCPI_MIN_LEN):
                                ti: int = attr_off + 4
                                ba: int = struct.unpack_from(
                                    "=Q", data, ti + _TCPI_BYTES_ACKED_OFF
                                )[0]
                                br: int = struct.unpack_from(
                                    "=Q", data,
                                    ti + _TCPI_BYTES_RECEIVED_OFF,
                                )[0]
                                results[inode] = (br, ba)
                            attr_off += (al + 3) & ~3
                    off += (nl_len + 3) & ~3
        _tcp_diag_available = True
    except OSError:
        _tcp_diag_available = False
        results = {}
    finally:
        sock.close()
    return results


def _net_io_tcp_diag(
    pids: list[int],
) -> tuple[float, float] | None:
    """Try to compute net bytes (recv, sent) via tcp_diag.

    Returns ``(net_recv, net_sent)`` or ``None`` if tcp_diag unavailable.
    """
    tcp_map: dict[int, tuple[int, int]] = _query_tcp_bytes()
    if not tcp_map:
        return None
    inodes: set[int] = _get_socket_inodes(pids)
    if not inodes:
        return (0.0, 0.0)
    total_recv: float = 0.0
    total_sent: float = 0.0
    for ino in inodes:
        entry = tcp_map.get(ino)
        if entry is not None:
            total_recv += entry[0]
            total_sent += entry[1]
    return (total_recv, total_sent)


def _net_io_rchar_fallback(pids: list[int]) -> tuple[float, float]:
    """Fallback: estimate net bytes via rchar-read_bytes for TCP-socket PIDs."""
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
    return (net_rchar, net_wchar)


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

    # Network I/O: delta-based via tcp_diag (accurate per-socket counters).
    # If tcp_diag is unavailable, leave at 0 — the rchar heuristic is too
    # inaccurate for processes doing heavy disk/pipe work.
    io_read: float = 0.0
    io_write: float = 0.0
    diag: tuple[float, float] | None = _net_io_tcp_diag(pids)
    if diag is not None:
        net_recv, net_sent = diag
        prev_io = _prev_proc_io.get(kitty_pid)
        if prev_io is not None:
            dt = now - prev_io[2]
            if dt > 0:
                io_read = max(0, (net_recv - prev_io[0]) / dt)
                io_write = max(0, (net_sent - prev_io[1]) / dt)
        _prev_proc_io[kitty_pid] = (net_recv, net_sent, now)

    return ProcessMetrics(
        cpu_pct=cpu_pct, ram_mb=ram_mb,
        gpu_pct=gpu_pct, gpu_mem_mb=gpu_mem,
        io_read_bps=io_read, io_write_bps=io_write,
    )
