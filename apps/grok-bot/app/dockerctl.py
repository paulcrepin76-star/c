"""Talk to the Docker engine on the Unraid host.

Reads go through the engine socket. Anything that needs a compose file
(install, update) shells out to `docker compose` in the repo directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import httpx

from app.settings import settings

EXTRA_FILE = "compose.extra.yml"


class DockerError(RuntimeError):
    pass


def socket_ready() -> bool:
    return os.path.exists(settings.docker_socket)


def _client(timeout: float = 60.0) -> httpx.Client:
    if not socket_ready():
        raise DockerError(f"No Docker socket at {settings.docker_socket}. Mount it into the bot container.")
    return httpx.Client(
        transport=httpx.HTTPTransport(uds=settings.docker_socket),
        base_url="http://docker",
        timeout=timeout,
    )


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message") or response.text)[:300]
    except Exception:  # noqa: BLE001
        return response.text[:300] or f"Docker returned {response.status_code}"


def _request(method: str, path: str, timeout: float = 60.0, **kwargs) -> httpx.Response:
    with _client(timeout) as client:
        response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        raise DockerError(_error_text(response))
    return response


def _health(status: str) -> str:
    """Docker writes `(healthy)`, `(unhealthy)`, or `(health: starting)`."""
    lowered = status.lower()
    for word in ("unhealthy", "healthy", "starting"):
        if f"({word})" in lowered or f"health: {word})" in lowered:
            return word
    return ""


def _ports(rows: list[dict]) -> list[str]:
    seen = []
    for row in rows:
        public = row.get("PublicPort")
        if not public:
            continue
        entry = f"{public}->{row.get('PrivatePort')}"
        if entry not in seen:
            seen.append(entry)
    return seen


def containers(include_stopped: bool = True) -> list[dict]:
    response = _request("GET", "/containers/json", params={"all": "1" if include_stopped else "0"})
    rows = []
    for item in response.json():
        labels = item.get("Labels") or {}
        rows.append(
            {
                "name": (item.get("Names") or ["/?"])[0].lstrip("/"),
                "image": item.get("Image", ""),
                "state": item.get("State", ""),
                "status": item.get("Status", ""),
                "health": _health(item.get("Status", "")),
                "ports": _ports(item.get("Ports") or []),
                "project": labels.get("com.docker.compose.project", ""),
                "service": labels.get("com.docker.compose.service", ""),
            }
        )
    return sorted(rows, key=lambda row: row["name"])


def find_container(name: str) -> dict | None:
    """Match what someone would text: `n8n`, `resto-n8n`, or the compose service."""
    wanted = (name or "").strip().lower().lstrip("/")
    if not wanted:
        return None
    rows = containers()
    for row in rows:
        if row["name"].lower() == wanted:
            return row
    for row in rows:
        if row["service"].lower() == wanted or row["name"].lower() == f"{settings.compose_project}-{wanted}":
            return row
    matches = [row for row in rows if wanted in row["name"].lower()]
    if len(matches) == 1:
        return matches[0]
    return None


def _demux(payload: bytes) -> str:
    """Docker frames non-TTY logs as 8-byte header + chunk."""
    out: list[str] = []
    index = 0
    while index + 8 <= len(payload):
        header = payload[index : index + 8]
        if header[0] not in (0, 1, 2) or header[1:4] != b"\x00\x00\x00":
            return payload.decode("utf-8", "replace")
        size = int.from_bytes(header[4:8], "big")
        index += 8
        out.append(payload[index : index + size].decode("utf-8", "replace"))
        index += size
    if not out:
        return payload.decode("utf-8", "replace")
    return "".join(out)


def logs(name: str, lines: int = 40) -> str:
    response = _request(
        "GET",
        f"/containers/{name}/logs",
        params={"stdout": "1", "stderr": "1", "tail": str(max(1, min(lines, 200)))},
    )
    return _demux(response.content).strip()


def lifecycle(name: str, action: str) -> None:
    if action not in ("start", "stop", "restart"):
        raise DockerError(f"Unknown action {action}")
    _request("POST", f"/containers/{name}/{action}", timeout=120.0)


def engine_info() -> dict:
    info = _request("GET", "/info").json()
    return {
        "docker_version": info.get("ServerVersion", ""),
        "containers": info.get("Containers", 0),
        "running": info.get("ContainersRunning", 0),
        "stopped": info.get("ContainersStopped", 0),
        "images": info.get("Images", 0),
        "cpus": info.get("NCPU", 0),
        "memory_gb": round((info.get("MemTotal") or 0) / 1024**3, 1),
        "os": info.get("OperatingSystem", ""),
    }


def _load_average() -> list[float]:
    try:
        with open("/proc/loadavg", encoding="utf-8") as handle:
            return [float(part) for part in handle.read().split()[:3]]
    except OSError:
        return []


def _memory_used_pct() -> float | None:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            values = {}
            for line in handle:
                key, _, rest = line.partition(":")
                values[key] = float(rest.strip().split()[0])
    except OSError:
        return None
    total = values.get("MemTotal") or 0
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    return round((total - available) / total * 100, 1)


def disk_usage(path: str = "") -> dict:
    target = path or settings.appdata_dir or "/"
    if not os.path.exists(target):
        target = "/"
    usage = shutil.disk_usage(target)
    return {
        "path": target,
        "total_gb": round(usage.total / 1024**3, 1),
        "used_gb": round((usage.total - usage.free) / 1024**3, 1),
        "free_gb": round(usage.free / 1024**3, 1),
        "used_pct": round((usage.total - usage.free) / usage.total * 100, 1) if usage.total else 0.0,
    }


def host_health() -> dict:
    return {
        "load": _load_average(),
        "memory_used_pct": _memory_used_pct(),
        "disk": disk_usage(),
    }


def compose_files() -> list[Path]:
    root = Path(settings.repo_dir)
    files = [root / "compose.yml"]
    extra = root / EXTRA_FILE
    if extra.exists():
        files.append(extra)
    return files


def _run(cmd: list[str], timeout: int, cwd: str) -> dict:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {"ok": False, "code": 127, "output": f"`{cmd[0]}` is not available inside the bot container."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": 124, "output": f"Gave up after {timeout} seconds."}
    except OSError as exc:
        return {"ok": False, "code": 1, "output": str(exc)[:300]}
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    return {"ok": proc.returncode == 0, "code": proc.returncode, "output": output}


def compose(*args: str, timeout: int | None = None) -> dict:
    root = Path(settings.repo_dir)
    if not (root / "compose.yml").exists():
        return {"ok": False, "code": 1, "output": f"No compose.yml under {root}. Set REPO_DIR to the stack folder."}
    files: list[str] = []
    for path in compose_files():
        files += ["-f", str(path)]
    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "--project-name",
        settings.compose_project,
        *files,
        *args,
    ]
    return _run(cmd, timeout or settings.compose_timeout, str(root))


def git_pull() -> dict:
    root = Path(settings.repo_dir)
    if not (root / ".git").exists():
        return {"ok": True, "code": 0, "output": "Not a git checkout, skipped the pull."}
    return _run(["git", "-C", str(root), "pull", "--ff-only"], 180, str(root))


def tail(text: str, limit: int = 1200) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return "…\n" + clean[-limit:]
