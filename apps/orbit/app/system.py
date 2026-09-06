"""Host vitals: CPU, RAM, disks, uptime."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

import psutil

from app.settings import settings

_last_cpu: tuple[float, dict[str, int]] | None = None


def _proc() -> Path:
    return Path(settings.host_proc)


def _read_cpu_times() -> dict[str, int] | None:
    stat = _proc() / "stat"
    try:
        line = stat.read_text().splitlines()[0]
    except OSError:
        return None
    parts = line.split()
    if parts[0] != "cpu" or len(parts) < 5:
        return None
    keys = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")
    values = [int(p) for p in parts[1:9]]
    return dict(zip(keys, values + [0] * (len(keys) - len(values))))


def _cpu_percent() -> float:
    global _last_cpu
    now = time.monotonic()
    sample = _read_cpu_times()
    if sample is None:
        return float(psutil.cpu_percent(interval=0.05))
    if _last_cpu is None:
        _last_cpu = (now, sample)
        time.sleep(0.08)
        sample = _read_cpu_times() or sample
        now = time.monotonic()
    prev_t, prev = _last_cpu
    _last_cpu = (now, sample)
    delta = {k: max(0, sample.get(k, 0) - prev.get(k, 0)) for k in sample}
    total = sum(delta.values())
    if total <= 0 or now - prev_t <= 0:
        return float(psutil.cpu_percent(interval=None) or 0)
    idle = delta.get("idle", 0) + delta.get("iowait", 0)
    return round(100.0 * (1 - idle / total), 1)


def _meminfo() -> dict[str, int]:
    path = _proc() / "meminfo"
    data: dict[str, int] = {}
    try:
        for line in path.read_text().splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            num = raw.strip().split()[0]
            if num.isdigit():
                data[key] = int(num) * 1024
    except OSError:
        virt = psutil.virtual_memory()
        return {"MemTotal": virt.total, "MemAvailable": virt.available}
    return data


def _uptime_seconds() -> int:
    try:
        return int(float((_proc() / "uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return int(time.time() - psutil.boot_time())


def _loadavg() -> list[float]:
    try:
        raw = (_proc() / "loadavg").read_text().split()[:3]
        return [round(float(x), 2) for x in raw]
    except (OSError, ValueError):
        return [round(x, 2) for x in os.getloadavg()]


def _disks() -> list[dict]:
    seen: set[str] = set()
    rows: list[dict] = []
    candidates = [Path("/")]
    for path in settings.root_map().values():
        candidates.append(path)
    shares = Path(settings.shares)
    if shares.exists():
        candidates.append(shares)
    for path in candidates:
        try:
            usage = psutil.disk_usage(str(path if path.exists() else "/"))
        except OSError:
            continue
        key = f"{usage.total}:{usage.used}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "name": path.name or "root",
                "path": str(path),
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.percent, 1),
            }
        )
        if len(rows) >= 4:
            break
    return rows


def snapshot() -> dict:
    mem = _meminfo()
    total = mem.get("MemTotal") or 1
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    used = max(0, total - available)
    percent = round(100.0 * used / total, 1)
    swap = psutil.swap_memory()
    hostname = settings.host_name
    try:
        host_name = (_proc().parent / "etc/hostname").read_text().strip()
        if host_name:
            hostname = host_name
    except OSError:
        hostname = settings.host_name or socket.gethostname()
    cpu_count = os.cpu_count() or psutil.cpu_count() or 1
    try:
        host_cpu = (_proc() / "cpuinfo").read_text()
        cpu_count = host_cpu.count("processor") or cpu_count
    except OSError:
        pass
    return {
        "host": hostname,
        "cpu": {
            "percent": _cpu_percent(),
            "cores": cpu_count,
            "load": _loadavg(),
        },
        "memory": {
            "percent": percent,
            "used": used,
            "total": total,
            "available": available,
        },
        "swap": {"percent": round(swap.percent, 1), "used": swap.used, "total": swap.total},
        "disks": _disks(),
        "uptime": _uptime_seconds(),
    }
