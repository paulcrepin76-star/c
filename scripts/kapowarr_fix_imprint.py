#!/usr/bin/env python3
"""Fix Kapowarr volumes that share an imprint root folder.

Those volumes steal every #1 (and more) under New 52 / Rebirth. This
unlinks the bad matches, points each volume at ``Series (Year)``, and
moves only a loose one-shot file that clearly belongs to that title.
Does not delete archives. Manga paths are ignored.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import kapowarr_cleanup as kc

IMPRINT_ROOTS = {
    "/comics/dc rebirth",
    "/comics/dc new 52",
    "/comics/absolute dc",
    "/comics/marvel",
    "/comics",
}

KAVITA_NAMING = {
    "volume_folder_naming": "{series_name} ({year})",
    "file_naming": "{series_name} ({year}) #{issue_number}",
    "file_naming_empty": "{series_name} ({year}) #{issue_number}",
    "file_naming_special_version": "{series_name} ({year}) {special_version}",
    "file_naming_vai": "{series_name} ({year}) #{issue_number}",
    "issue_padding": 3,
    "volume_padding": 2,
}

HOST_COMICS = "/mnt/user/media/book/comics"
CONTAINER_COMICS = "/comics"


def is_imprint_root_folder(folder: str) -> bool:
    return kc.folder_key(folder).lower() in IMPRINT_ROOTS


def sanitize_folder_name(name: str) -> str:
    text = (name or "").strip()
    text = text.replace("/", "-").replace(":", " -")
    text = re.sub(r'[<>"|?*]', "", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text


def target_volume_folder(title: str, year: int | None, current_folder: str) -> str:
    """Return a container path that is unique to this series, not the imprint."""
    parent = kc.folder_key(current_folder)
    if not is_imprint_root_folder(parent):
        return parent
    if parent.lower() in {"/comics", "/comics/marvel", "/comics/absolute dc"}:
        parent = CONTAINER_COMICS
    label = sanitize_folder_name(title)
    if year:
        label = f"{label} ({int(year)})"
    return f"{parent}/{label}"


def normalize_match(text: str) -> str:
    value = (text or "").lower().replace("&", " and ")
    value = re.sub(r"\b(19|20)\d{2}\b", " ", value)
    value = re.sub(r"\b(vo|os|fcbd|digital)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def loose_file_score(title: str, filename: str) -> int:
    wanted = normalize_match(title)
    have = normalize_match(Path(filename).stem)
    if not wanted or not have:
        return 0
    leftover = have
    for token in wanted.split():
        leftover = leftover.replace(token, "", 1)
    leftover = re.sub(r"\s+", " ", leftover).strip()
    if leftover.isdigit():
        return 0
    if wanted == have or wanted.replace(" ", "") == have.replace(" ", ""):
        return 100
    if wanted in have or have in wanted:
        return 85
    wt, ht = set(wanted.split()), set(have.split())
    if not wt or not ht:
        return 0
    overlap = len(wt & ht)
    if overlap < 2:
        return 0
    return int(100 * overlap / len(wt | ht))


def pick_loose_file(title: str, filenames: list[str]) -> str | None:
    """Pick one loose imprint file for a one-shot title, or none if ambiguous."""
    scored = [(loose_file_score(title, name), name) for name in filenames]
    scored = [row for row in scored if row[0] >= 80]
    scored.sort(key=lambda row: (-row[0], row[1]))
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    if len(scored) > 1 and scored[0][0] < 100 and scored[1][0] >= 80:
        return None
    return scored[0][1]


def container_to_host(path: str) -> str:
    text = path.rstrip("/")
    if text == CONTAINER_COMICS or text.startswith(CONTAINER_COMICS + "/"):
        return HOST_COMICS + text[len(CONTAINER_COMICS) :]
    return text


def host_to_container(path: str) -> str:
    text = path.rstrip("/")
    if text == HOST_COMICS or text.startswith(HOST_COMICS + "/"):
        return CONTAINER_COMICS + text[len(HOST_COMICS) :]
    return text


def plan_imprint_fix(
    volumes: list[dict],
    loose_files_by_root: dict[str, list[str]],
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for volume in volumes:
        folder = str(volume.get("folder") or "")
        if not is_imprint_root_folder(folder):
            continue
        if kc.is_manga_path(folder):
            continue
        root = kc.folder_key(folder)
        target = target_volume_folder(str(volume.get("title") or ""), volume.get("year"), folder)
        move_from = None
        if (volume.get("issue_count") or 1) <= 1:
            move_from = pick_loose_file(str(volume.get("title") or ""), loose_files_by_root.get(root.lower(), []))
        plan.append(
            {
                "id": int(volume["id"]),
                "title": volume.get("title"),
                "year": volume.get("year"),
                "from_folder": root,
                "to_folder": target,
                "move_from": move_from,
                "move_to": f"{target}/{Path(move_from).name}" if move_from else None,
                "issue_count": volume.get("issue_count") or 0,
            }
        )
    return plan


def apply_naming(client: kc.Kapowarr) -> dict:
    status, payload = client.request("PUT", "/settings", body=KAVITA_NAMING)
    if status >= 400:
        raise RuntimeError(f"PUT /settings HTTP {status}: {payload}")
    return payload.get("result") or payload


def refresh_volume(client: kc.Kapowarr, volume_id: int) -> dict:
    status, payload = client.request(
        "POST",
        "/system/tasks",
        body={"cmd": "refresh_and_scan", "volume_id": int(volume_id)},
    )
    if status >= 400:
        raise RuntimeError(f"refresh_and_scan {volume_id} HTTP {status}: {payload}")
    return payload.get("result") or payload


def ssh(command: str) -> str:
    result = subprocess.run(
        ["sudo", "tailscale", "ssh", "root@lerouxfamily", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def apply_plan_on_host(plan: list[dict[str, Any]], *, dry_run: bool) -> None:
    sql_lines = ["BEGIN;"]
    for item in plan:
        vid = int(item["id"])
        sql_lines.append(
            f"DELETE FROM issues_files WHERE issue_id IN (SELECT id FROM issues WHERE volume_id={vid});"
        )
        sql_lines.append(f"DELETE FROM volume_files WHERE volume_id={vid};")
        folder = str(item["to_folder"]).replace("'", "''")
        sql_lines.append(
            f"UPDATE volumes SET folder='{folder}', custom_folder=1 WHERE id={vid};"
        )
        if item.get("move_from") and item.get("move_to"):
            old = str(item["move_from"]).replace("'", "''")
            new = str(item["move_to"]).replace("'", "''")
            sql_lines.append(
                f"UPDATE files SET filepath='{new}' WHERE filepath='{old}';"
            )
    sql_lines.append("COMMIT;")
    sql = "\n".join(sql_lines)
    if dry_run:
        print(sql, flush=True)
        return
    Path("/tmp/kapowarr-fix-imprint.sql").write_text(sql + "\n", encoding="utf-8")
    subprocess.run(
        ["sudo", "tailscale", "ssh", "root@lerouxfamily", "cat > /tmp/kapowarr-fix-imprint.sql"],
        input=sql + "\n",
        text=True,
        check=True,
    )
    ssh("sqlite3 /mnt/user/appdata/kapowarr/Kapowarr.db < /tmp/kapowarr-fix-imprint.sql")
    for item in plan:
        if not item.get("move_from") or not item.get("move_to"):
            continue
        src = container_to_host(str(item["move_from"]))
        dst_dir = container_to_host(str(Path(item["move_to"]).parent))
        dst = container_to_host(str(item["move_to"]))
        ssh(f"mkdir -p {json.dumps(dst_dir)} && mv -n {json.dumps(src)} {json.dumps(dst)}")


def list_loose_files() -> dict[str, list[str]]:
    raw = ssh(
        "find '/mnt/user/media/book/comics/DC New 52' '/mnt/user/media/book/comics/dc rebirth' "
        "-maxdepth 1 -type f \\( -iname '*.cbr' -o -iname '*.cbz' -o -iname '*.cb7' \\) | sort"
    )
    by_root: dict[str, list[str]] = {
        "/comics/dc new 52": [],
        "/comics/dc rebirth": [],
    }
    for line in raw.splitlines():
        container = host_to_container(line.strip())
        parent = str(Path(container).parent)
        by_root.setdefault(parent.lower(), []).append(container)
    return by_root


def cmd_run(client: kc.Kapowarr, dry_run: bool, out: str | None) -> int:
    volumes = client.volumes()
    loose = list_loose_files()
    plan = plan_imprint_fix(volumes, loose)
    report = {
        "before": client.stats(),
        "plan": plan,
        "naming": KAVITA_NAMING,
    }
    print(json.dumps({"planned": len(plan), "moves": sum(1 for i in plan if i.get("move_from"))}, indent=2), flush=True)
    for item in plan:
        print(
            f"vol {item['id']} {item['title']} ({item['year']}) "
            f"{item['from_folder']} -> {item['to_folder']}"
            + (f" move {Path(item['move_from']).name}" if item.get("move_from") else ""),
            flush=True,
        )
    if not dry_run:
        apply_naming(client)
        apply_plan_on_host(plan, dry_run=False)
        for item in plan:
            try:
                refresh_volume(client, int(item["id"]))
            except Exception as exc:
                print(f"scan {item['id']} {exc}", flush=True)
        try:
            refresh_volume(client, 314)
        except Exception as exc:
            print(f"scan Action Comics 2011 {exc}", flush=True)
        volumes = client.volumes()
        report["after"] = {
            "stats": client.stats(),
            "imprint_left": [
                {"id": v["id"], "title": v.get("title"), "folder": v.get("folder")}
                for v in volumes
                if is_imprint_root_folder(str(v.get("folder") or ""))
            ],
            "action_2011": next(
                (
                    {
                        "id": v["id"],
                        "downloaded": v.get("issues_downloaded"),
                        "issues": v.get("issue_count"),
                        "folder": v.get("folder"),
                    }
                    for v in volumes
                    if v.get("id") == 314
                ),
                None,
            ),
        }
    text = json.dumps(report, indent=2)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("KAPOWARR_URL", "http://127.0.0.1:5656/api"))
    parser.add_argument("--api-key-file", default=os.environ.get("KAPOWARR_API_KEY_FILE"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    client = kc.Kapowarr(args.url, kc.load_key(args.api_key_file))
    return cmd_run(client, args.dry_run, args.out)


if __name__ == "__main__":
    raise SystemExit(main())

