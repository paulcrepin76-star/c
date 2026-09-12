#!/usr/bin/env python3
"""Set Comicarr qBittorrent keys from a Sonarr DownloadClients Settings JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path

SONARR = Path("/tmp/qbit-sonarr.json")
INI = Path("/config/comicarr/config.ini")


def set_key(text: str, key: str, value: str) -> str:
    pattern = rf"(?m)^({re.escape(key)}\s*=\s*).*$"
    if not re.search(pattern, text):
        raise SystemExit(f"missing key {key}")
    return re.sub(pattern, lambda m: m.group(1) + value, text, count=1)


def qbit_url(settings: dict) -> str:
    host = settings["host"]
    port = int(settings["port"])
    ssl = bool(settings["useSsl"])
    scheme = "https" if ssl else "http"
    if ssl and port == 443:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def main() -> int:
    settings = json.loads(SONARR.read_text())
    url = qbit_url(settings)
    text = INI.read_text()
    text = set_key(text, "torrent_downloader", "5")
    text = set_key(text, "enable_torrents", "True")
    text = set_key(text, "enable_torrent_search", "True")
    text = set_key(text, "file_opts", "copy")
    text = set_key(text, "qbittorrent_host", url)
    text = set_key(text, "qbittorrent_username", settings["username"])
    text = set_key(text, "qbittorrent_password", settings["password"])
    text = set_key(text, "qbittorrent_label", "manga")
    text = set_key(text, "qbittorrent_folder", "/home/deicide/Downloads/manga")
    text = set_key(text, "qbittorrent_loadaction", "default")
    INI.write_text(text)
    print("host", url)
    print("user", settings["username"])
    print("label manga")
    print("folder /home/deicide/Downloads/manga")
    print("pass_len", len(settings["password"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
