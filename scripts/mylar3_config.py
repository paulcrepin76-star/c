#!/usr/bin/env python3
"""Patch Mylar3 config.ini without printing secrets.

Mylar3 folder tokens use ``$Series``, so interpolation must stay off.
"""
from __future__ import annotations

import argparse
import configparser
import json
import secrets
import sys
from pathlib import Path

COMIC_LOCATION = "/comics"
DOWNLOADS = "/downloads"
FOLDER_FORMAT = "$Series ($Year)"
FILE_FORMAT = "$Series ($Year) #$Issue"
SECRET_KEYS = frozenset(
    {
        "comicvine_api",
        "api_key",
        "http_password",
        "http_username",
        "git_token",
        "sab_apikey",
        "nzbget_password",
        "prowlarr_apikey",
        "qbittorrent_password",
        "transmission_password",
        "deluge_password",
        "rtorrent_password",
        "utorrent_password",
        "seedbox_pass",
        "opds_password",
        "email_password",
        "discord_webhook",
        "slack_webhook",
        "telegram_token",
        "pushover_apikey",
        "pushover_userkey",
        "pushbullet_apikey",
        "boxcar_token",
        "gotify_token",
        "prowl_keys",
    }
)


def empty(value: str | None) -> bool:
    return value is None or str(value).strip() in {"", "None", "none", "null"}


def ini_bool(value: bool) -> str:
    return "True" if value else "False"


def load_ini(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = lambda option: option.lower()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        cfg.read_string(text)
    return cfg


def ensure_section(cfg: configparser.ConfigParser, name: str) -> None:
    if not cfg.has_section(name):
        cfg.add_section(name)


def get(cfg: configparser.ConfigParser, section: str, key: str) -> str:
    if not cfg.has_option(section, key):
        return ""
    return str(cfg.get(section, key))


def set_opt(cfg: configparser.ConfigParser, section: str, key: str, value: str) -> None:
    ensure_section(cfg, section)
    cfg.set(section, key, value)


def read_secret_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    return raw.strip()


def apply_safe_defaults(
    cfg: configparser.ConfigParser,
    *,
    comicvine: str | None = None,
    api_key: str | None = None,
) -> None:
    set_opt(cfg, "General", "destination_dir", COMIC_LOCATION)
    set_opt(cfg, "General", "multiple_dest_dirs", "None")
    set_opt(cfg, "General", "rename_files", ini_bool(False))
    set_opt(cfg, "General", "move_files", ini_bool(False))
    set_opt(cfg, "General", "create_folders", ini_bool(True))
    set_opt(cfg, "General", "folder_format", FOLDER_FORMAT)
    set_opt(cfg, "General", "file_format", FILE_FORMAT)
    set_opt(cfg, "General", "launch_browser", ini_bool(False))
    set_opt(cfg, "General", "nzb_startup_search", ini_bool(False))
    set_opt(cfg, "Interface", "http_host", "0.0.0.0")
    set_opt(cfg, "Interface", "http_port", "8090")
    set_opt(cfg, "Perms", "enforce_perms", ini_bool(False))
    set_opt(cfg, "Import", "add_comics", ini_bool(False))
    set_opt(cfg, "Import", "comic_dir", "None")
    set_opt(cfg, "Import", "imp_move", ini_bool(False))
    set_opt(cfg, "Import", "imp_rename", ini_bool(False))
    set_opt(cfg, "Import", "imp_paths", ini_bool(False))
    set_opt(cfg, "PostProcess", "enable_check_folder", ini_bool(False))
    set_opt(cfg, "DDL", "ddl_location", DOWNLOADS)
    set_opt(cfg, "CV", "cvapi_rate", "3")
    set_opt(cfg, "API", "api_enabled", ini_bool(True))

    current_key = get(cfg, "API", "api_key")
    if api_key:
        set_opt(cfg, "API", "api_key", api_key)
    elif empty(current_key):
        set_opt(cfg, "API", "api_key", secrets.token_hex(16))

    if comicvine:
        set_opt(cfg, "CV", "comicvine_api", comicvine)


def summary(cfg: configparser.ConfigParser) -> dict:
    dest = get(cfg, "General", "destination_dir")
    ddl = get(cfg, "DDL", "ddl_location")
    return {
        "destination_dir": dest if not empty(dest) else COMIC_LOCATION,
        "ddl_location": ddl if not empty(ddl) else DOWNLOADS,
        "folder_format": get(cfg, "General", "folder_format") or FOLDER_FORMAT,
        "file_format": get(cfg, "General", "file_format") or FILE_FORMAT,
        "rename_files": get(cfg, "General", "rename_files") == "True",
        "move_files": get(cfg, "General", "move_files") == "True",
        "enforce_perms": get(cfg, "Perms", "enforce_perms") == "True",
        "add_comics": get(cfg, "Import", "add_comics") == "True",
        "imp_rename": get(cfg, "Import", "imp_rename") == "True",
        "imp_move": get(cfg, "Import", "imp_move") == "True",
        "api_enabled": get(cfg, "API", "api_enabled") == "True",
        "has_api_key": not empty(get(cfg, "API", "api_key")),
        "has_comicvine_api": not empty(get(cfg, "CV", "comicvine_api")),
        "multiple_dest_dirs": get(cfg, "General", "multiple_dest_dirs"),
    }


def write_ini(cfg: configparser.ConfigParser, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        cfg.write(handle)


def apply(
    path: Path,
    *,
    comicvine_file: Path | None = None,
    api_key_out: Path | None = None,
) -> dict:
    cfg = load_ini(path)
    comicvine = None
    if comicvine_file is not None:
        comicvine = read_secret_file(comicvine_file)
        if empty(comicvine):
            comicvine = None
    apply_safe_defaults(cfg, comicvine=comicvine)
    write_ini(cfg, path)
    if api_key_out is not None:
        key = get(cfg, "API", "api_key")
        api_key_out.write_text(key + "\n", encoding="utf-8")
        api_key_out.chmod(0o600)
    data = summary(cfg)
    if SECRET_KEYS.intersection(data):
        raise RuntimeError("summary included a secret key name")
    dumped = json.dumps(data)
    for section, key in (("CV", "comicvine_api"), ("API", "api_key")):
        value = get(cfg, section, key)
        if value and not empty(value) and value in dumped:
            raise RuntimeError("summary leaked a secret value")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("apply", "summary"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--comicvine-file")
    parser.add_argument("--api-key-out")
    args = parser.parse_args(argv)
    path = Path(args.config)
    if args.command == "summary":
        json.dump(summary(load_ini(path)), sys.stdout)
        sys.stdout.write("\n")
        return 0
    cv_file = Path(args.comicvine_file) if args.comicvine_file else None
    key_out = Path(args.api_key_out) if args.api_key_out else None
    json.dump(apply(path, comicvine_file=cv_file, api_key_out=key_out), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
