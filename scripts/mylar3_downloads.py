#!/usr/bin/env python3
"""Wire Mylar3 grab clients without printing secrets.

ComicVine stays the catalog. GetComics DDL is the same source Kapowarr uses.
SABnzbd and the Whatbox qBittorrent profile come from Sonarr. Prowlarr
indexers are added as Newznab/Torznab. JDownloader is left off.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import mylar3_config as mc

SKIP_INDEXERS = {"nyaa.si", "nyaa manga english"}
PROWLARR_BASE = "http://prowlarr:9696"
SAB_HOST = "http://sabnzbd:8080"
SAB_CATEGORY = "comics"
QBIT_LABEL = "comics"
QBIT_FOLDER = "/home/deicide/Downloads/comics"
FLARESOLVERR = "http://flaresolverr:8191"
NEWZNAB_CATEGORY = "7030"


def qbit_url(settings: dict) -> str:
    host = str(settings.get("host") or "").strip()
    port = int(settings.get("port") or 0)
    ssl = bool(settings.get("useSsl"))
    scheme = "https" if ssl else "http"
    if ssl and port in {0, 443}:
        return f"{scheme}://{host}"
    if not ssl and port in {0, 80}:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def flatten_extras(rows: list[tuple]) -> str:
    flat: list[str] = []
    for row in rows:
        for item in row:
            flat.append("" if item is None else str(item))
    return ", ".join(flat)


def extras_from_prowlarr(indexers: list[dict], api_key: str) -> tuple[list[tuple], list[tuple]]:
    newznabs: list[tuple] = []
    torznabs: list[tuple] = []
    next_id = 1
    for indexer in indexers:
        name = str(indexer.get("Name") or "").strip()
        if not name or name.lower() in SKIP_INDEXERS:
            continue
        if not indexer.get("Enable"):
            continue
        indexer_id = int(indexer["Id"])
        url = f"{PROWLARR_BASE}/{indexer_id}/api"
        kind = str(indexer.get("Implementation") or "")
        row = (name, url, api_key, "1", NEWZNAB_CATEGORY if kind == "Newznab" else "", "1", next_id)
        next_id += 1
        if kind == "Newznab":
            newznabs.append(row)
        else:
            torznabs.append(row)
    return newznabs, torznabs


def read_prowlarr_key(path: Path) -> str:
    root = ET.parse(path).getroot()
    key = root.findtext("ApiKey") or root.findtext("apiKey") or ""
    return key.strip()


def read_json_row(db: Path, sql: str) -> dict:
    raw = sqlite3.connect(str(db)).execute(sql).fetchone()
    if not raw or not raw[0]:
        return {}
    return json.loads(raw[0])


def read_prowlarr_indexers(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT Id, Name, Implementation, Enable FROM Indexers ORDER BY Id").fetchall()
    return [
        {"Id": int(row[0]), "Name": row[1], "Implementation": row[2], "Enable": bool(row[3])}
        for row in rows
    ]


def apply_download_clients(
    cfg,
    *,
    sab: dict,
    qbit: dict,
    newznabs: list[tuple],
    torznabs: list[tuple],
) -> None:
    mc.set_opt(cfg, "General", "rename_files", mc.ini_bool(False))
    mc.set_opt(cfg, "General", "move_files", mc.ini_bool(True))
    mc.set_opt(cfg, "General", "autowant_upcoming", mc.ini_bool(False))
    mc.set_opt(cfg, "General", "autowant_all", mc.ini_bool(False))
    mc.set_opt(cfg, "General", "nzb_startup_search", mc.ini_bool(False))
    mc.set_opt(cfg, "Import", "imp_move", mc.ini_bool(False))
    mc.set_opt(cfg, "Import", "imp_rename", mc.ini_bool(False))
    mc.set_opt(cfg, "Import", "imp_paths", mc.ini_bool(True))

    mc.set_opt(cfg, "DDL", "enable_ddl", mc.ini_bool(True))
    mc.set_opt(cfg, "DDL", "enable_getcomics", mc.ini_bool(True))
    mc.set_opt(cfg, "DDL", "ddl_location", mc.DOWNLOADS)
    mc.set_opt(cfg, "DDL", "enable_flaresolverr", mc.ini_bool(True))
    mc.set_opt(cfg, "DDL", "flaresolverr_url", FLARESOLVERR)
    mc.set_opt(cfg, "DDL", "jd2_enable", mc.ini_bool(False))
    mc.set_opt(cfg, "DDL", "enable_external_server", mc.ini_bool(False))

    mc.set_opt(cfg, "Client", "nzb_downloader", "0" if sab.get("apiKey") else "3")
    mc.set_opt(cfg, "Client", "torrent_downloader", "5" if qbit.get("password") else "0")

    if sab.get("apiKey"):
        mc.set_opt(cfg, "SABnzbd", "sab_host", SAB_HOST)
        mc.set_opt(cfg, "SABnzbd", "sab_apikey", str(sab["apiKey"]))
        mc.set_opt(cfg, "SABnzbd", "sab_category", SAB_CATEGORY)
        mc.set_opt(cfg, "SABnzbd", "sab_to_mylar", mc.ini_bool(False))
        mc.set_opt(cfg, "SABnzbd", "sab_directory", "/data/downloads/complete/comics")
        mc.set_opt(cfg, "SABnzbd", "sab_client_post_processing", mc.ini_bool(False))

    if qbit.get("host"):
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_host", qbit_url(qbit))
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_username", str(qbit.get("username") or ""))
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_password", str(qbit.get("password") or ""))
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_label", QBIT_LABEL)
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_folder", QBIT_FOLDER)
        mc.set_opt(cfg, "qBittorrent", "qbittorrent_ignore_ssl", mc.ini_bool(True))
        mc.set_opt(cfg, "Torrents", "enable_torrents", mc.ini_bool(True))
        mc.set_opt(cfg, "Torrents", "enable_torrent_search", mc.ini_bool(True))

    mc.set_opt(cfg, "Newznab", "newznab", mc.ini_bool(bool(newznabs)))
    mc.set_opt(cfg, "Newznab", "extra_newznabs", flatten_extras(newznabs))
    mc.set_opt(cfg, "Torznab", "enable_torznab", mc.ini_bool(bool(torznabs)))
    mc.set_opt(cfg, "Torznab", "extra_torznabs", flatten_extras(torznabs))


def download_summary(cfg) -> dict:
    data = mc.summary(cfg)
    extra_n = mc.get(cfg, "Newznab", "extra_newznabs")
    extra_t = mc.get(cfg, "Torznab", "extra_torznabs")
    data.update(
        {
            "newznab_providers": 0 if mc.empty(extra_n) else extra_n.count("http://"),
            "torznab_providers": 0 if mc.empty(extra_t) else extra_t.count("http://"),
            "sab_category": mc.get(cfg, "SABnzbd", "sab_category"),
            "qbit_label": mc.get(cfg, "qBittorrent", "qbittorrent_label"),
            "qbit_folder": mc.get(cfg, "qBittorrent", "qbittorrent_folder"),
            "flaresolverr_url": mc.get(cfg, "DDL", "flaresolverr_url"),
        }
    )
    dumped = json.dumps(data)
    for section, key in (
        ("CV", "comicvine_api"),
        ("API", "api_key"),
        ("SABnzbd", "sab_apikey"),
        ("qBittorrent", "qbittorrent_password"),
        ("qBittorrent", "qbittorrent_host"),
        ("Newznab", "extra_newznabs"),
        ("Torznab", "extra_torznabs"),
    ):
        value = mc.get(cfg, section, key)
        if value and not mc.empty(value) and value not in {"True", "False", "None"} and value in dumped:
            raise RuntimeError("download summary leaked a secret value")
    return data


def apply(path: Path, *, sonarr_db: Path, prowlarr_db: Path, prowlarr_config: Path) -> dict:
    cfg = mc.load_ini(path)
    sab = read_json_row(
        sonarr_db, "SELECT Settings FROM DownloadClients WHERE Implementation='Sabnzbd' LIMIT 1"
    )
    qbit = read_json_row(
        sonarr_db, "SELECT Settings FROM DownloadClients WHERE Implementation='QBittorrent' LIMIT 1"
    )
    api_key = read_prowlarr_key(prowlarr_config)
    newznabs, torznabs = extras_from_prowlarr(read_prowlarr_indexers(prowlarr_db), api_key)
    apply_download_clients(cfg, sab=sab, qbit=qbit, newznabs=newznabs, torznabs=torznabs)
    mc.write_ini(cfg, path)
    return download_summary(cfg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("apply", "summary"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--sonarr-db")
    parser.add_argument("--prowlarr-db")
    parser.add_argument("--prowlarr-config")
    args = parser.parse_args(argv)
    path = Path(args.config)
    if args.command == "summary":
        json.dump(download_summary(mc.load_ini(path)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if not args.sonarr_db or not args.prowlarr_db or not args.prowlarr_config:
        raise SystemExit("apply needs --sonarr-db --prowlarr-db --prowlarr-config")
    json.dump(
        apply(
            path,
            sonarr_db=Path(args.sonarr_db),
            prowlarr_db=Path(args.prowlarr_db),
            prowlarr_config=Path(args.prowlarr_config),
        ),
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
