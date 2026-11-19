#!/usr/bin/env python3
"""Read-only host checks for the marketing stack.

Does not start containers, edit ZFS datasets, change share settings, or run sysctl.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# recordsize is per workload. A shared 128K dataset is reported, not rejected.
WORKLOADS = (
    ("mautic/mysql", "mysql", 16, "MySQL InnoDB pages are 16K."),
    ("postiz/postgres", "postgres", 16, "Postgres pages are 8K, and 16K is the matching ZFS recordsize."),
    ("temporal/postgres", "postgres", 16, "Temporal's Postgres uses the same 16K recordsize."),
    ("temporal/elasticsearch", "search", 128, "Elasticsearch segment files are large, so 128K fits them."),
    ("postiz/uploads", "media", 1024, "Photos and video are sequential, so 1M fits them."),
    ("mautic/media/files", "media", 1024, "Mautic files are larger than database pages."),
    ("mautic/media/images", "media", 1024, "Mautic images are larger than database pages."),
    ("postiz/redis", "small", 16, "Redis persistence is small. 16K or the pool default both work."),
    ("postiz/config", "small", 128, "Config files can stay on a 128K dataset."),
    ("mautic/config", "small", 128, "Config files can stay on a 128K dataset."),
    ("mautic/logs", "logs", 128, "Logs are append-only. 128K fits them."),
    ("command", "files", 128, "Menu files are mixed. 128K fits them."),
)

TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
# Docker's built-in local pools. Each new bridge takes one subnet of `size` bits.
DEFAULT_LOCAL_POOLS = (
    ("172.17.0.0/16", 16),
    ("172.18.0.0/16", 16),
    ("172.19.0.0/16", 16),
    ("172.20.0.0/14", 16),
    ("172.24.0.0/14", 16),
    ("172.28.0.0/14", 16),
    ("192.168.0.0/16", 20),
)
# Peak marketing containers that would hold an address on the resto network at once.
MARKETING_ADDRESS_NEED = 16


def parse_share(share_cfg: str) -> dict[str, str]:
    """Read Unraid 6.12+ / 7.x Primary storage and Secondary storage.

    The share file still stores shareUseCache. The UI labels are:
    only -> Primary pool, Secondary None
    yes -> Primary pool, Secondary Array, mover pool to array
    prefer -> Primary pool, Secondary Array, mover array to pool
    no -> Primary Array, Secondary None
    shareCachePool2 set -> Secondary is that pool
    """
    primary = _cfg_value(share_cfg, "shareCachePool")
    secondary_pool = _cfg_value(share_cfg, "shareCachePool2")
    use = _cfg_value(share_cfg, "shareUseCache")
    if secondary_pool:
        primary_kind, secondary_kind = "pool", "pool"
        secondary_label = secondary_pool
    elif use == "only":
        primary_kind, secondary_kind = "pool", "none"
        secondary_label = "None"
    elif use == "yes":
        primary_kind = "pool" if primary else "array"
        secondary_kind = "array"
        secondary_label = "Array, mover from pool to array"
    elif use == "prefer":
        primary_kind = "pool" if primary else "array"
        secondary_kind = "array"
        secondary_label = "Array, mover from array to pool"
    elif use == "no" or not primary:
        primary_kind, secondary_kind = "array", "none"
        secondary_label = "None"
        primary = primary or "array"
    else:
        primary_kind, secondary_kind = "unknown", "unknown"
        secondary_label = "unreadable"
    return {
        "primary": primary,
        "primary_kind": primary_kind,
        "secondary_kind": secondary_kind,
        "secondary_pool": secondary_pool,
        "secondary_label": secondary_label,
        "use_cache": use,
    }


def assess_storage(
    appdata: str,
    share_cfg: str | None,
    unraid: bool,
    transports: dict[str, set[str]] | None = None,
    array_paths: list[str] | None = None,
    pool_paths: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    transports = transports or {}
    array_paths = array_paths or []
    pool_paths = pool_paths or []
    raw = appdata or "."
    path = os.path.realpath(raw) if os.path.exists(raw) else raw
    if _on_array(path):
        errors.append(f"{path} is on an Unraid array disk. Marketing data belongs on the NVMe pool.")
        return notes, errors
    if not unraid:
        notes.append("Not an Unraid host, so Primary storage and Secondary storage were not read.")
        return notes, errors
    if not (path.startswith("/mnt/user/appdata") or re.match(r"^/mnt/[^/]+/appdata(?:/|$)", path)):
        errors.append(
            f"{path} is not under /mnt/user/appdata or a pool's appdata directory. Set APPDATA to the NVMe-backed appdata share."
        )
    if share_cfg is None:
        errors.append(
            "Unraid share config /boot/config/shares/appdata.cfg is not readable, so Primary storage and Secondary storage cannot be confirmed."
        )
        return notes, errors
    share = parse_share(share_cfg)
    notes.append(
        f"Primary storage: {share['primary'] or 'unset'} ({share['primary_kind']}). Secondary storage: {share['secondary_label']}."
    )
    if share["primary_kind"] != "pool" or not share["primary"] or share["primary"] == "array":
        errors.append("Primary storage is the array or is unset. Set Primary storage to the NVMe pool.")
    elif share["secondary_kind"] == "array":
        errors.append(
            "Secondary storage is the array. The mover can place database files on HDDs. Set Secondary storage to None."
        )
    elif share["secondary_kind"] == "pool":
        errors.append(
            f"Secondary storage is pool {share['secondary_pool']}. Set Secondary storage to None so marketing data stays on the primary pool."
        )
    elif share["secondary_kind"] != "none":
        errors.append("Secondary storage could not be read. Set Secondary storage to None.")
    pool = share["primary"]
    if share["primary_kind"] == "pool" and pool and pool != "array":
        found = transports.get(pool)
        if not found:
            errors.append(f"The disks behind pool {pool} were not identified, so NVMe is not confirmed.")
        elif found != {"nvme"}:
            errors.append(f"Pool {pool} disks report {', '.join(sorted(found))}, not nvme.")
        else:
            notes.append(f"Pool {pool} is on NVMe.")
    if array_paths:
        errors.append("These paths already exist on the array: " + ", ".join(array_paths))
    if pool_paths:
        notes.append("These paths are on the pool: " + ", ".join(pool_paths))
    return notes, errors


def assess_zfs(rows: list[dict[str, str]], appdata: str) -> tuple[list[str], list[str]]:
    """Describe recordsize per workload. Never returns a blocking error and never changes a dataset."""
    notes: list[str] = []
    if not rows:
        notes.append("No ZFS datasets were reported. If the cache pool is ZFS, rerun this on the Unraid host. No dataset was changed.")
        return notes, []
    for rel, kind, want, why in WORKLOADS:
        target = appdata.rstrip("/") + "/" + rel
        match = _dataset_for(rows, target) or _dataset_for(rows, appdata)
        if match is None and "/mnt/user/" in appdata:
            suffix = appdata.split("/mnt/user/", 1)[1]
            for row in rows:
                mount = (row.get("mountpoint") or "").rstrip("/")
                if mount.endswith("/" + suffix) or mount.endswith(suffix):
                    match = row
                    break
        if match is None:
            notes.append(f"{rel}: no ZFS dataset matches this path. {why} No dataset was changed.")
            continue
        actual = _size_kib(match.get("recordsize", ""))
        label = f"{match.get('name')} recordsize={match.get('recordsize')}"
        if kind in {"mysql", "postgres"} and actual not in {None, want}:
            notes.append(
                f"{rel} sits on {label}. {why} A child dataset at 16K would match this database. The existing dataset is left as it is."
            )
        elif kind == "media" and actual is not None and actual < 128:
            notes.append(
                f"{rel} sits on {label}. {why} A child dataset at 1M would fit these files. The existing dataset is left as it is."
            )
        else:
            notes.append(f"{rel} sits on {label}. {why}")
    notes.append("Preflight does not run zfs create or zfs set.")
    return notes, []


def assess_bind(bind: str, assigned: list[str] | None, unraid: bool) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    errors: list[str] = []
    if bind in {"0.0.0.0", "::", ""}:
        errors.append("BIND_ADDR publishes on every interface. The LAN and a port forward could reach these ports.")
        return notes, errors
    if bind == "127.0.0.1":
        if unraid:
            errors.append(
                "BIND_ADDR is 127.0.0.1. Phones on Tailscale could not open the dashboard. Set BIND_ADDR to the Tailscale IPv4."
            )
        else:
            notes.append("BIND_ADDR is 127.0.0.1. That is local to this machine, not a Tailscale path.")
        return notes, errors
    try:
        ip = ipaddress.ip_address(bind)
    except ValueError:
        errors.append(f"BIND_ADDR {bind} is not an IP address.")
        return notes, errors
    if ip in TAILSCALE_V4:
        notes.append(
            f"{bind} is in the Tailscale range 100.64.0.0/10. Published ports listen on that address only, not on 0.0.0.0."
        )
        if assigned is not None and bind not in assigned:
            errors.append(f"{bind} is not assigned on this host, so Tailscale is down or the address changed.")
        return notes, errors
    errors.append(
        f"{bind} is not a Tailscale address. Binding there would expose the port on that interface. Use the 100.x Tailscale address."
    )
    return notes, errors


def assess_resources(
    mem_available_kb: int | None,
    load1: float | None,
    cpus: int,
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
                f"Only {gib:.1f} GiB is available. The full marketing stack needs about 6 GiB free before Postiz starts. No memory cap is set."
            )
    if load1 is not None:
        notes.append(f"Load average 1 minute {load1:.2f} on {cpus} CPUs")
        if cpus > 0 and load1 > cpus * 2:
            errors.append(
                f"Load average {load1:.2f} is above twice the CPU count ({cpus}). Inspect the host before adding Temporal and Elasticsearch."
            )
    return notes, errors


def pool_subnets(pools: list[tuple[str, int]] | None) -> list[ipaddress.IPv4Network]:
    """Expand Docker local address pools into the subnets a new bridge would be offered, in order."""
    chosen = list(pools) if pools else list(DEFAULT_LOCAL_POOLS)
    found: list[ipaddress.IPv4Network] = []
    for base, size in chosen:
        network = ipaddress.ip_network(base, strict=False)
        if not isinstance(network, ipaddress.IPv4Network):
            continue
        if size < network.prefixlen or size > 32:
            continue
        count = 1 << (size - network.prefixlen)
        shift = 32 - size
        start = int(network.network_address)
        for index in range(count):
            found.append(ipaddress.ip_network((start + (index << shift), size)))
    return found


def assess_networks(
    records: list[dict] | None,
    pools: list[tuple[str, int]] | None,
    host_routes: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Decide whether marketing can join the resto network or, only if it is missing, allocate one subnet.

    Marketing compose marks resto as external and sets no static container address.
    This function does not create a network.
    """
    notes: list[str] = []
    errors: list[str] = []
    if records is None:
        notes.append("Docker is not available, so network subnets were not read.")
        return notes, errors
    occupied: list[ipaddress.IPv4Network] = []
    parsed: list[tuple[dict, list[ipaddress.IPv4Network]]] = []
    for record in records:
        subnets: list[ipaddress.IPv4Network] = []
        for raw in record.get("subnets") or []:
            try:
                network = ipaddress.ip_network(raw, strict=False)
            except ValueError:
                notes.append(f"{record.get('name')}: subnet {raw} could not be parsed.")
                continue
            if isinstance(network, ipaddress.IPv4Network):
                subnets.append(network)
                occupied.append(network)
        parsed.append((record, subnets))
        rendered = ", ".join(str(item) for item in subnets) or "no IPv4 subnet"
        attached = ", ".join(record.get("attached") or []) or "none"
        notes.append(
            f"Network {record.get('name')} driver={record.get('driver') or 'unknown'} "
            f"subnet={rendered} attached={record.get('used', 0)} ({attached})."
        )
    for left_index, (left, left_nets) in enumerate(parsed):
        for right, right_nets in parsed[left_index + 1 :]:
            for left_net in left_nets:
                for right_net in right_nets:
                    if left_net.overlaps(right_net):
                        errors.append(
                            f"Docker networks {left.get('name')} {left_net} and {right.get('name')} {right_net} overlap."
                        )
    routes: list[ipaddress.IPv4Network] = []
    for raw in host_routes or []:
        try:
            route = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if isinstance(route, ipaddress.IPv4Network):
            routes.append(route)
    resto = next((item for item in parsed if item[0].get("name") == "resto"), None)
    if resto is not None:
        record, subnets = resto
        driver = record.get("driver") or ""
        notes.append(
            "Marketing joins the existing resto network. It does not create a second network and does not set container addresses."
        )
        if driver in {"host", "null"}:
            errors.append(f"The resto network uses the {driver} driver. Marketing expects a bridge, macvlan, or ipvlan network.")
            return notes, errors
        if not subnets:
            errors.append("The resto network has no IPv4 subnet, so new containers would not get addresses.")
            return notes, errors
        for subnet in subnets:
            reserved = 2 if subnet.prefixlen <= 30 else 0
            free = subnet.num_addresses - reserved - int(record.get("used") or 0)
            notes.append(f"resto {subnet} has about {free} free IPv4 addresses after {record.get('used', 0)} attached containers.")
            if free < MARKETING_ADDRESS_NEED:
                errors.append(
                    f"resto {subnet} has about {free} free addresses. The full marketing stack needs {MARKETING_ADDRESS_NEED}."
                )
            for route in routes:
                if subnet.overlaps(route) and driver == "bridge":
                    errors.append(
                        f"resto bridge subnet {subnet} overlaps host route {route}. Containers on that bridge could not reach that route."
                    )
                elif subnet.overlaps(route):
                    notes.append(
                        f"resto {driver} subnet {subnet} is on host route {route}. Joining it does not allocate a new Docker subnet."
                    )
        return notes, errors
    notes.append("The resto network is absent. An approved start would create one bridge named resto, and only if it is still missing.")
    candidates = pool_subnets(pools)
    pool_label = "daemon address pools" if pools else "Docker's built-in local pools"
    free_subnet = None
    for candidate in candidates:
        if any(candidate.overlaps(item) for item in occupied):
            continue
        if any(candidate.overlaps(route) for route in routes):
            continue
        free_subnet = candidate
        break
    if free_subnet is None:
        errors.append(
            f"No free IPv4 subnet remains in {pool_label}. Creating the resto network would fail. This check does not prune networks."
        )
    else:
        notes.append(
            f"The first free subnet in {pool_label} is {free_subnet}. "
            "Inspection does not create it. Existing container addresses stay where they are."
        )
    return notes, errors


def assess_ports(bind: str, holders: dict[int, str], stage: str) -> list[str]:
    expected = {8084: "resto-mautic", 4007: "resto-postiz", 8090: "resto-command", 8085: "resto-temporal-ui"}
    if stage == "mautic":
        expected = {8084: expected[8084]}
    elif stage == "postiz":
        expected = {4007: expected[4007], 8085: expected[8085]}
    elif stage == "dashboard":
        expected = {8090: expected[8090]}
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


def assess_map_count(value: int, stage: str) -> str | None:
    if value >= 262144 or stage == "mautic":
        return None
    return (
        f"vm.max_map_count is {value}. Elasticsearch, used by the Postiz stage, needs 262144. "
        "This script will not change the kernel. On Unraid run: sysctl -w vm.max_map_count=262144 "
        "and add that line to /boot/config/go."
    )


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


def placement(appdata: str, pool: str) -> tuple[list[str], list[str]]:
    """Find marketing paths that already exist on array disks or on the named pool. Read-only."""
    if "/mnt/user/" not in appdata:
        return [], []
    rel = appdata.split("/mnt/user/", 1)[1].strip("/")
    array: list[str] = []
    pools: list[str] = []
    root = Path("/mnt")
    if not root.is_dir():
        return [], []
    relatives = [rel] + [f"{rel}/{name}" for name in ("mautic", "postiz", "temporal", "command", "caddy")]
    for entry in root.iterdir():
        name = entry.name
        on_array = name.startswith("disk") and name[4:].isdigit()
        on_pool = bool(pool) and name == pool
        if not on_array and not on_pool:
            continue
        for item in relatives:
            candidate = entry / item
            if candidate.exists():
                (array if on_array else pools).append(str(candidate))
    return array, pools


def _cfg_value(text: str, key: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(key + "="):
            return stripped.split("=", 1)[1].strip().strip('"')
    return ""


def _on_array(path: str) -> bool:
    parts = path.split("/")
    if any(part.startswith("disk") and part[4:].isdigit() for part in parts):
        return True
    return "/mnt/disk" in path


def _dataset_for(rows: list[dict[str, str]], path: str) -> dict[str, str] | None:
    best: dict[str, str] | None = None
    best_len = -1
    for row in rows:
        mount = row.get("mountpoint") or ""
        if mount in {"", "-", "none"}:
            continue
        mount = mount.rstrip("/")
        if path == mount or path.startswith(mount + "/"):
            if len(mount) > best_len:
                best = row
                best_len = len(mount)
    return best


def _size_kib(value: str) -> int | None:
    text = (value or "").strip().upper()
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


def _local_ipv4() -> list[str]:
    try:
        output = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return []
    return re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)/", output)


def _docker_networks() -> tuple[list[dict] | None, dict[int, str], list[str]]:
    try:
        listing = subprocess.check_output(["docker", "network", "ls", "-q"], text=True)
    except (OSError, subprocess.CalledProcessError):
        return None, {}, []
    ids = [line.strip() for line in listing.splitlines() if line.strip()]
    records: list[dict] = []
    if ids:
        try:
            raw = subprocess.check_output(["docker", "network", "inspect", *ids], text=True)
            records = _parse_network_inspect(json.loads(raw))
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            records = []
    holders: dict[int, str] = {}
    containers: list[str] = []
    try:
        ps = subprocess.check_output(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"], text=True)
    except (OSError, subprocess.CalledProcessError):
        ps = ""
    for line in ps.splitlines():
        containers.append(line)
        name, _, rest = line.partition("\t")
        _status, _, ports = rest.partition("\t")
        for port in (8084, 4007, 8090, 8085):
            if f":{port}->" in ports:
                holders[port] = name
    return records, holders, containers


def _parse_network_inspect(data: list) -> list[dict]:
    records = []
    for item in data:
        subnets = []
        for cfg in (item.get("IPAM") or {}).get("Config") or []:
            subnet = cfg.get("Subnet")
            if subnet:
                subnets.append(subnet)
        attached = []
        for container in (item.get("Containers") or {}).values():
            name = container.get("Name")
            if name:
                attached.append(name)
        records.append(
            {
                "name": item.get("Name") or "",
                "driver": item.get("Driver") or "",
                "subnets": subnets,
                "used": len(item.get("Containers") or {}),
                "attached": attached,
            }
        )
    return records


def _address_pools() -> list[tuple[str, int]] | None:
    path = Path("/etc/docker/daemon.json")
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    pools = payload.get("default-address-pools")
    if not isinstance(pools, list) or not pools:
        return None
    parsed: list[tuple[str, int]] = []
    for pool in pools:
        if not isinstance(pool, dict) or "base" not in pool or "size" not in pool:
            continue
        try:
            parsed.append((str(pool["base"]), int(pool["size"])))
        except (TypeError, ValueError):
            continue
    return parsed or None


def _nondocker_routes() -> list[str]:
    try:
        output = subprocess.check_output(["ip", "-4", "route"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return []
    routes = []
    for line in output.splitlines():
        if " dev docker0" in line or " dev br-" in line:
            continue
        parts = line.split()
        if not parts or parts[0] == "default" or "/" not in parts[0]:
            continue
        routes.append(parts[0])
    return routes


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


def _pool_transports(pool: str) -> set[str] | None:
    devices = _pool_devices(pool)
    if not devices:
        return None
    found: set[str] = set()
    for device in devices:
        base = device
        if base.startswith("nvme"):
            found.add("nvme")
            continue
        rotational = Path(f"/sys/block/{base}/queue/rotational")
        try:
            flag = rotational.read_text(encoding="utf-8").strip()
        except OSError:
            found.add("unknown")
            continue
        found.add("hdd" if flag == "1" else "ssd")
    return found or None


def _pool_devices(pool: str) -> list[str]:
    text = ""
    try:
        text = subprocess.check_output(["zpool", "status", pool], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        text = ""
    if not text:
        try:
            text = subprocess.check_output(["findmnt", "-n", "-o", "SOURCE", f"/mnt/{pool}"], text=True, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            text = ""
    names = re.findall(r"\b((?:nvme\d+n\d+|sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+))", text)
    unique = []
    for name in names:
        if name not in unique:
            unique.append(name)
    return unique


def main() -> int:
    print("Read-only preflight. No container will be started, no dataset will be changed, and sysctl will not be run.")
    appdata = os.environ.get("APPDATA") or str(ROOT / "appdata")
    unraid = os.path.isdir("/mnt/user")
    stage = os.environ.get("MARKETING_STAGE", "")
    cfg_path = Path("/boot/config/shares/appdata.cfg")
    share_cfg = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    ack_load = os.environ.get("MARKETING_LOAD_ACK") == "1"
    ack_memory = os.environ.get("MARKETING_MEMORY_ACK") == "1"
    bind = os.environ.get("BIND_ADDR") or "127.0.0.1"

    print(f"App data: {appdata}")
    print(f"Stage filter: {stage or 'all ports and the Postiz kernel check'}")
    if not unraid:
        print("This machine has no /mnt/user. Storage, ZFS, CPU, and RAM figures below are for this machine, not the Unraid server.")
    errors: list[str] = []
    share = parse_share(share_cfg) if share_cfg else None
    pool = share["primary"] if share and share["primary_kind"] == "pool" else ""
    array_hits, pool_hits = placement(appdata, pool) if unraid else ([], [])
    transports: dict[str, set[str]] = {}
    if unraid and pool:
        detected = _pool_transports(pool)
        if detected is not None:
            transports[pool] = detected
    storage_notes, storage_errors = assess_storage(
        appdata,
        share_cfg,
        unraid,
        transports=transports,
        array_paths=array_hits,
        pool_paths=pool_hits,
    )
    for note in storage_notes:
        print(note)
    errors.extend(storage_errors)

    disk_note, disk_error = assess_disk(appdata)
    print(disk_note)
    if disk_error:
        errors.append(disk_error)

    zfs_notes, _zfs_errors = assess_zfs(_zfs_rows(), appdata)
    for note in zfs_notes:
        print(note)

    records, holders, containers = _docker_networks()
    if containers:
        print("Existing containers, inspected only:")
        for line in containers:
            print(f"  {line}")
    elif records is None:
        print("Docker is not available, so existing containers were not listed.")
    else:
        print("Docker reported no containers.")
    network_notes, network_errors = assess_networks(records, _address_pools(), _nondocker_routes())
    for note in network_notes:
        print(note)
    errors.extend(network_errors)
    resource_notes, resource_errors = assess_resources(_mem_available(), _load(), _cpus())
    for note in resource_notes:
        print(note)
    for item in resource_errors:
        if "GiB" in item and ack_memory:
            print("Memory acknowledgment accepted. " + item)
        elif "Load average" in item and ack_load:
            print("Load acknowledgment accepted. " + item)
        else:
            errors.append(item)

    map_value = _map_count()
    print(f"vm.max_map_count={map_value}")
    map_error = assess_map_count(map_value, stage)
    if map_error:
        errors.append(map_error)
    elif stage == "mautic" and map_value < 262144:
        print("Mautic stage does not start Elasticsearch. Raise vm.max_map_count before the Postiz stage.")

    bind_notes, bind_errors = assess_bind(bind, _local_ipv4(), unraid)
    for note in bind_notes:
        print(note)
    errors.extend(bind_errors)
    errors.extend(assess_ports(bind, holders, stage))
    print("The public Caddy edge is not part of this check and is not started.")

    print("Planning range once Mautic, Postiz, and the dashboard are idle: about 3 to 5 GB resident, and about 6 to 8 GB during a campaign or video upload.")
    print("Mautic alone is about 1 to 2 GB. Postiz with Temporal and Elasticsearch adds about 2 to 4 GB.")
    print("No container memory cap is set. A tight cap is more likely to kill a campaign send than to save RAM.")
    if errors:
        print("Preflight refused. No container was started and no host setting was changed.")
        print("\n".join(errors))
        return 2
    print("Preflight finished. No container was started and no host setting was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
