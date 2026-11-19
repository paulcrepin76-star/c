#!/usr/bin/env python3
"""Read-only host checks for the marketing stack. Does not start containers or change sysctls."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assess_storage(appdata: str, share_cfg: str | None, unraid: bool) -> list[str]:
    errors: list[str] = []
    raw = appdata or "."
    path = os.path.realpath(raw) if os.path.exists(raw) else raw
    parts = path.split("/")
    if "disk" in parts and any(part.startswith("disk") and part[4:].isdigit() for part in parts):
        errors.append(f"{path} is on an Unraid array disk. Database files belong on the cache pool.")
    if "/mnt/disk" in path:
        errors.append(f"{path} is under /mnt/disk. Refusing to put marketing data on the HDD array.")
    if not unraid:
        return errors
    if not (path.startswith("/mnt/user/appdata") or path.startswith("/mnt/cache") or path.startswith("/mnt/nvme")):
        errors.append(
            f"{path} is not under /mnt/user/appdata or a cache mount. Set APPDATA to the NVMe-backed appdata share."
        )
    if share_cfg is None:
        errors.append("Unraid share config /boot/config/shares/appdata.cfg is not readable, so cache-only cannot be confirmed.")
        return errors
    use_cache = _cfg_value(share_cfg, "shareUseCache")
    pool = _cfg_value(share_cfg, "shareCachePool") or "cache"
    if use_cache != "only":
        errors.append(
            f"appdata shareUseCache is {use_cache or 'unset'}. It must be only, or the mover can place databases on the array. Pool name in the file: {pool}."
        )
    return errors


def assess_zfs(rows: list[dict[str, str]], appdata: str) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    if not rows:
        notes.append("No ZFS datasets were reported. If the cache pool is ZFS, install the tools and rerun this on the Unraid host.")
        return notes, errors
    path = os.path.realpath(appdata) if appdata and os.path.exists(appdata) else appdata
    match = _dataset_for(rows, path)
    if match is None and path.startswith("/mnt/user/"):
        for candidate in ("/mnt/cache/appdata", "/mnt/nvme/appdata"):
            match = _dataset_for(rows, candidate)
            if match:
                notes.append(f"User share path {path} maps to dataset check on {candidate}.")
                break
    if match is None:
        notes.append("No ZFS dataset mountpoint matches the appdata path.")
        return notes, errors
    record = match.get("recordsize", "")
    notes.append(
        "ZFS dataset {name} mount {mountpoint} recordsize={recordsize} compression={compression} sync={sync} logbias={logbias} primarycache={primarycache} atime={atime}".format(
            **{key: match.get(key, "") for key in ("name", "mountpoint", "recordsize", "compression", "sync", "logbias", "primarycache", "atime")}
        )
    )
    kib = _size_kib(record)
    if kib is not None and kib > 16:
        errors.append(
            f"Dataset {match.get('name')} recordsize is {record}. Postgres and MySQL want 16K. "
            "Create child datasets before the first start, for example: "
            "zfs create -o recordsize=16K -o primarycache=metadata -o atime=off -o logbias=throughput <pool>/appdata/resto/mautic "
            "and the same for postiz and temporal. This script does not create datasets or change properties."
        )
    return notes, errors


def assess_resources(
    mem_available_kb: int | None,
    load1: float | None,
    cpus: int,
    network_count: int | None,
    resto_network: bool | None,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    if mem_available_kb is None:
        notes.append("MemAvailable was not readable.")
    else:
        gib = mem_available_kb / (1024 * 1024)
        notes.append(f"MemAvailable {gib:.1f} GiB")
        if mem_available_kb < 6 * 1024 * 1024:
            errors.append(
                f"Only {gib:.1f} GiB is available. The marketing stack needs about 6 GiB free before it starts. No memory cap is set."
            )
    if load1 is not None:
        notes.append(f"Load average 1 minute {load1:.2f} on {cpus} CPUs")
        if cpus > 0 and load1 > cpus * 2:
            errors.append(
                f"Load average {load1:.2f} is above twice the CPU count ({cpus}). Inspect the host before adding Temporal and Elasticsearch."
            )
    if network_count is None:
        notes.append("Docker is not available, so network-pool usage was not counted.")
    else:
        notes.append(f"Docker networks: {network_count}. resto network present: {bool(resto_network)}")
        if resto_network is False and network_count >= 30:
            errors.append(
                f"The resto network does not exist and Docker already has {network_count} networks. "
                "Creating another one can fail when the address pools are exhausted. This script does not prune networks."
            )
    return notes, errors


def assess_ports(bind: str, holders: dict[int, str]) -> list[str]:
    expected = {8084: "resto-mautic", 4007: "resto-postiz", 8090: "resto-command", 8085: "resto-temporal-ui"}
    errors = []
    for port, owner in expected.items():
        holder = holders.get(port)
        if holder and holder != owner:
            errors.append(f"Port {port} is published by {holder}, not {owner}.")
            continue
        if holder == owner:
            continue
        sock = socket.socket()
        try:
            taken = sock.connect_ex((bind, port)) == 0
        except OSError as exc:
            errors.append(f"Could not check {bind}:{port} ({exc.__class__.__name__}).")
            continue
        finally:
            sock.close()
        if taken:
            errors.append(f"{bind}:{port} is already accepting connections.")
    return errors


def assess_map_count(value: int) -> str | None:
    if value < 262144:
        return (
            f"vm.max_map_count is {value}. Elasticsearch needs 262144. "
            "This script will not change the kernel. On Unraid run: sysctl -w vm.max_map_count=262144 "
            "and add that line to /boot/config/go."
        )
    return None


def assess_disk(path: str) -> tuple[str, str | None]:
    target = path if os.path.isdir(path) else os.path.dirname(path) or "."
    usage = shutil.disk_usage(target if os.path.isdir(target) else ".")
    free_gb = usage.free / (1024 ** 3)
    note = f"Free space beside app data: {free_gb:.1f} GB"
    if free_gb < 8:
        return note, "Need at least 8 GB free for images and databases."
    if free_gb < 20:
        return note + " Warning: under 20 GB free. Mautic media and Postiz uploads will need more later.", None
    return note, None


def _cfg_value(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _dataset_for(rows: list[dict[str, str]], path: str) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    best_len = -1
    for row in rows:
        mount = row.get("mountpoint") or ""
        if mount in {"", "-", "none"}:
            continue
        if path == mount or path.startswith(mount.rstrip("/") + "/"):
            if len(mount) > best_len:
                best = row
                best_len = len(mount)
    return best


def _size_kib(value: str) -> int | None:
    text = value.strip().upper()
    if text.endswith("K") and text[:-1].isdigit():
        return int(text[:-1])
    if text.endswith("M") and text[:-1].isdigit():
        return int(text[:-1]) * 1024
    return None


def _mem_available() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def _load() -> float | None:
    try:
        return float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _cpus() -> int:
    return os.cpu_count() or 1


def _map_count() -> int:
    try:
        return int(Path("/proc/sys/vm/max_map_count").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _docker_networks() -> tuple[int | None, bool | None, dict[int, str]]:
    try:
        listing = subprocess.check_output(["docker", "network", "ls", "--format", "{{.Name}}"], text=True)
    except (OSError, subprocess.CalledProcessError):
        return None, None, {}
    names = [line.strip() for line in listing.splitlines() if line.strip()]
    holders: dict[int, str] = {}
    try:
        ps = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"], text=True)
    except (OSError, subprocess.CalledProcessError):
        ps = ""
    for line in ps.splitlines():
        name, _, ports = line.partition("\t")
        for port in (8084, 4007, 8090, 8085):
            if f":{port}->" in ports:
                holders[port] = name
    return len(names), "resto" in names, holders


def _zfs_rows() -> list[dict[str, str]]:
    try:
        output = subprocess.check_output(
            ["zfs", "list", "-H", "-o", "name,mountpoint,recordsize,compression,sync,logbias,primarycache,atime"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    rows = []
    keys = ["name", "mountpoint", "recordsize", "compression", "sync", "logbias", "primarycache", "atime"]
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= len(keys):
            rows.append(dict(zip(keys, parts)))
    return rows


def main() -> int:
    appdata = os.environ.get("APPDATA") or str(ROOT / "appdata")
    unraid = os.path.isdir("/mnt/user")
    cfg_path = Path("/boot/config/shares/appdata.cfg")
    share_cfg = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    ack_storage = os.environ.get("MARKETING_STORAGE_ACK") == "1"
    ack_zfs = os.environ.get("MARKETING_ZFS_ACK") == "1"
    ack_load = os.environ.get("MARKETING_LOAD_ACK") == "1"
    ack_memory = os.environ.get("MARKETING_MEMORY_ACK") == "1"
    bind = os.environ.get("BIND_ADDR") or "127.0.0.1"

    print(f"App data: {appdata}")
    if not unraid:
        print("This machine has no /mnt/user. Storage, ZFS, CPU, and RAM figures below are for this machine, not the Unraid server.")
    errors: list[str] = []
    storage_errors = assess_storage(appdata, share_cfg, unraid)
    if storage_errors and not (ack_storage and not any("HDD array" in item or "/mnt/disk" in item for item in storage_errors)):
        errors.extend(storage_errors)
    elif storage_errors and ack_storage:
        print("Storage acknowledgment accepted for non-array warnings:")
        print("\n".join(storage_errors))

    disk_note, disk_error = assess_disk(appdata)
    print(disk_note)
    if disk_error:
        errors.append(disk_error)

    zfs_notes, zfs_errors = assess_zfs(_zfs_rows(), appdata)
    for note in zfs_notes:
        print(note)
    if zfs_errors and not ack_zfs:
        errors.extend(zfs_errors)
    elif zfs_errors:
        print("ZFS recordsize acknowledgment accepted. Properties were not changed.")

    networks, resto, holders = _docker_networks()
    resource_notes, resource_errors = assess_resources(_mem_available(), _load(), _cpus(), networks, resto)
    for note in resource_notes:
        print(note)
    for item in resource_errors:
        if "GiB" in item and ack_memory:
            print("Memory acknowledgment accepted. " + item)
        elif "Load average" in item and ack_load:
            print("Load acknowledgment accepted. " + item)
        else:
            errors.append(item)

    map_error = assess_map_count(_map_count())
    print(f"vm.max_map_count={_map_count()}")
    if map_error:
        errors.append(map_error)
    errors.extend(assess_ports(bind, holders))

    print("Planning range once the stack is idle: about 3 to 5 GB resident, and about 6 to 8 GB while a campaign or video upload is running.")
    print("No container memory cap is set. A tight cap is more likely to kill a campaign send than to save RAM.")
    if errors:
        print("Preflight refused. No container was started.")
        print("\n".join(errors))
        return 2
    print("Preflight finished. No container was started and no host setting was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
