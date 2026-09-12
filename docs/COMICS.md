# Comics and manga on Unraid

Kapowarr and Comicarr do not browse the disk the way Kavita does. They only
keep series that match ComicVine (Kapowarr) or ComicVine / MangaDex (Comicarr).
The files live under imprint folders (`DC Comics`, `dc rebirth`, `Shueisha`),
so a first-level scan of `/comics` or `/manga` sees publishers, not series.

## What is on the box

| Role | App | URL |
| --- | --- | --- |
| Read | Kavita | `http://100.116.48.120:5001` |
| Manga grabs | Comicarr | `http://100.116.48.120:8090` |
| Comic grabs | Kapowarr | `http://100.116.48.120:5656` |

| Host path | Container path | App |
| --- | --- | --- |
| `/mnt/user/media/book/comics` | `/comics` | Kapowarr |
| `/mnt/user/media/book/manga` | `/manga` | Comicarr, Kavita |
| `/mnt/user/media/book` | `/books` | Kavita |
| `/mnt/remotes/whatbox/Downloads` | `/home/deicide/Downloads` | Comicarr (seedbox qBittorrent) |
| `/mnt/user/appdata/comicarr/disabled-comics` | `/comics` | Comicarr dummy so it cannot see comics |

Comicarr uses the same Whatbox qBittorrent as Sonarr/Radarr/Prowlarr
(`https://qbittorrent.niftycurlew.box.ca`, category `manga`). Completed
files land in `/mnt/remotes/whatbox/Downloads/manga`. Post-process
**copies** them into `/manga` so the seedbox can keep seeding.

If Comicarr is recreated, copy the qBittorrent profile again with:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/comicarr-qbittorrent.sh
```

Then open a manga → Interactive Search. Packs need **Allow packs** on that
series. Do not point Comicarr at the whole Whatbox Downloads folder.

Kavita (`http://100.116.48.120:5001`) is the reader. Comicarr is
`http://100.116.48.120:8090`. Kapowarr is `http://100.116.48.120:5656`.

Open Kavita to read the folders that are already on disk. Kapowarr and
Comicarr are grabbers; they will never list 600 imprint folders the way a
reader does.

The Kavita **Manga** library already has MPD Psycho, Bleach, One Piece, and
Shangri-La Frontier. Add the comic tiles with:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/kavita-add-libraries.sh
```

That creates one Kavita library per tree (Absolute DC, DC New 52, DC Rebirth,
Marvel, Spider-Man, DC Comics) and queues a scan. Files stay where they are.
Do not add `/books/comics` as a single root: that would also pick up
`.comicarr-scan`.

## Import the existing library

On Unraid, from this repo:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
git pull
bash scripts/comicarr-fix-libraries.sh
bash scripts/run-library-imports.sh
```

`comicarr-fix-libraries.sh` builds `/comics/.comicarr-scan` and
`/manga/.comicarr-scan` as real series folders of file-level symlinks. It does
not move or rename the archives. Leave **Import** / **move** / **rename** off.

`run-library-imports.sh` then:

- Scans both Comicarr Import tiles and confirms every matched series
- Rebinds each new Comicarr series to the real folder (so empty
  `$Series ($Year)` folders are not left at the comics root)
- Walks Kapowarr Library Import one series folder at a time, **Import** only
- Adds `/manga` as a Kapowarr root when that mount exists

ComicVine is rate-limited (~200 requests/hour). Do not run Comicarr and
Kapowarr imports at the same time. A 420 (`Slow down cowboy`) means wait
an hour and run `scripts/comicarr_import.py --only comic` again. Already
imported series stay; new ComicVine matches get added and rebound.

Unmatched rows stay unmatched: French/Spanish editions, dump folders, and
most manga will not become Kapowarr volumes. Manga in Comicarr uses MangaDex.

## Why the library looked empty

- Comicarr Import only matches **first-level** folders of `comic_dir` /
  `manga_dir`. Imprint names (`Marvel`, `Shueisha`) do not match.
- Directory symlinks are invisible to Comicarr's `os.walk`.
- Kapowarr only imports files in a **subfolder** of a root, defaulting to 20
  folders and English-only ComicVine matches.
- Kapowarr will never list the manga tree unless `/manga` is mounted and added
  as a second root. Even then ComicVine drops most of it.

Use **Import**. Do not use **Import and Rename** on a folder Kavita already
reads. Rename moves files into grabber-owned volume folders.

## Check visibility without SSH

```bash
bash scripts/comics-visibility.sh
```

That replays the last saved snapshot.

## Resume a partial ComicVine pass

The indexer found **563** comic series folders and **5** manga series with
files. ComicVine will not finish that in one hour. After the cap resets:

```bash
docker cp scripts/comicarr_import.py comicarr:/tmp/comicarr_import.py
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_import.py --only comic
docker exec comicarr /opt/comicarr/.venv/bin/python /tmp/comicarr_import_matches.py
```

Then import only the newly matched folders into Kapowarr with
`scripts/kapowarr_import_known.py`. Leave move/rename off.
