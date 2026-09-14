# Comics and manga on Unraid

Kavita reads the folders on disk. Rensaio grabs **manga**. Kapowarr
grabs **comics**. Do not turn on Rensaio **Rename** or Kapowarr
**Import and Rename** on a folder Kavita already reads.

## What is on the box

| Role | App | URL |
| --- | --- | --- |
| Read | Kavita | `http://100.116.48.120:5001` |
| Manga grabs | Rensaio | `http://100.116.48.120:9833` |
| Comic grabs | Kapowarr | `http://100.116.48.120:5656` |

| Host path | Container path | App |
| --- | --- | --- |
| `/mnt/user/media/book/comics` | `/comics` | Kapowarr |
| `/mnt/user/media/book/manga` | `/series` | Rensaio |
| `/mnt/user/media/book/manga` | `/manga` | Kavita |
| `/mnt/user/media/book` | `/books` | Kavita |

Rensaio uses Mihon website extensions (MangaDex, MangaFire, Weeb Central,
VIZ). It is not Prowlarr / qBittorrent. Official Jump apps only have the
chapters they currently license, so a search that “finds” Bleach on VIZ
still cannot grab the full run. Pick the **MangaFire** or **Weeb Central**
row, not the first catalog dump. FlareSolverr must be
`http://flaresolverr:8191` (not `127.0.0.1`) or Weeb Central stays empty.

Clear a stuck queue (failed Weeb Central retries clog downloads) with:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/rensaio-queue.sh status
bash scripts/rensaio-queue.sh clean
```

Do not turn on Rensaio **Rename**. New chapters land under
`/mnt/user/media/book/manga`.

If Rensaio is recreated:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/rensaio-install.sh
bash scripts/rensaio-search.sh
```

Comicarr was removed. It found complete packs through Prowlarr / Nyaa,
which is why famous titles looked easier there. Do not start it again
unless asked; it fights Kapowarr for the same folders. Appdata is kept
as `/mnt/user/appdata/comicarr-backup-*`. Manga files were not
deleted. Mylar3 was removed (container, appdata, and
`/mnt/user/downloads/mylar3`). Comic files were not deleted. The leftover
`scripts/mylar3-*.sh` helpers refuse to run. Do not reinstall Mylar3
unless asked. Port `8090` is free.

Open Kavita to read the folders that are already on disk. The Kavita
**Manga** library already has MPD Psycho, Bleach, One Piece, and
Shangri-La Frontier. Add the comic tiles with:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/kavita-add-libraries.sh
```

That creates one Kavita library per tree (Absolute DC, DC New 52, DC Rebirth,
Marvel, Spider-Man, DC Comics) and queues a scan. Files stay where they are.
Do not add `/books/comics` as a single root.

## Kapowarr comics

Kapowarr only imports files in a **subfolder** of a root. ComicVine is
rate-limited (~200 requests/hour). A 420 (`Slow down cowboy`) means wait
an hour.

For a full cleanup (empty archives, empty duplicate volume *records*,
then import unmatched files into the volume they already belong to):

```bash
# From the Cloud Agent, Kapowarr is proxied at http://127.0.0.1:5656
bash scripts/kapowarr-cleanup.sh inventory --out /tmp/kapowarr-inventory.json
bash scripts/kapowarr-cleanup.sh run --search-all --out /tmp/kapowarr-cleanup.json
```

That script never deletes a volume folder. It only deletes comic
archives that are empty or under 1 KB, and Kapowarr volume rows that
are empty one-shot twins of a populated title in the same folder. A
later run that still has many undownloaded issues (Batman Beyond 2016
next to 2012) is kept. It renames a file only when it is a
Rebirth-numbered issue sitting in a golden-age folder (Action Comics
#957+ in the 1938 folder). Manga paths are ignored.

Search All only uses GetComics. FlareSolverr is already installed
(`ghcr.io/flaresolverr/flaresolverr:latest`, no host port). It starts
on `manga-net` only, so Kapowarr and Prowlarr cannot see it until it
is also attached to `kapowarr_default` and `media-net`:

```bash
ssh root@100.116.48.120
bash /mnt/user/appdata/resto/scripts/flaresolverr-attach.sh
```

Kapowarr Settings → FlareSolverr Base URL should be
`http://flaresolverr:8191` (no `/v1`). Prowlarr needs a FlareSolverr
indexer proxy on that same URL, tagged on indexers that use Cloudflare
(Torrent9).

A first-time import of folders that have no volume yet still uses
Library Import. Prefer **Import** so files stay where Kavita reads
them. Use **Import and Rename** only for a small, verified batch that
is in the wrong series folder. Kapowarr's own volume search returns
nothing, so missing folders are matched through ComicVine (`name:`
filter only; the search endpoint 420s) and imported in place:

```bash
# From the Cloud Agent, after listing unmatched /comics folders
bash scripts/kapowarr-cleanup.sh unmatched \
  --folders-file /tmp/unmatched-folders.txt \
  --out /tmp/kapowarr-unmatched.json
```

That skips manga, the Marvel NOW preview dump, and foreign reprint
trees (ECC, Novaro, Panini, Urban, …). It does not rename files.

Kapowarr naming is set for Kavita later: series folder
`{series_name} ({year})`, files `{series_name} ({year}) #{issue_number}`.
Volumes must not share an imprint root (`/comics/DC New 52`,
`/comics/dc rebirth`). The imprint fix unlinks stolen matches, moves
only a clearly matching loose one-shot, and rematches files in the new
folder (no ComicVine call). Short titles do not steal leftovers
(`Teen Titans` will not take `Teen Titans (2014) Futures End`).

```bash
python3 scripts/kapowarr_fix_imprint.py --out /tmp/kapowarr-imprint-fix.json
```

Do not run unmatched import until imprint-root volumes are gone.

The empty **DC Rebirth Omnibus (2016)** row was leftover from the old
Omnibus container (`omnibus` / `omnibus-engine` / `omnibus-redis` on
`/mnt/user/omnibus-data`). That share is gone, Kapowarr now reads
`/mnt/user/media/book/comics`, and there is no hardcover archive on
disk. The imprint fix deletes that volume record (`delete_folder=false`)
and removes only the empty folder it created. Add the book again if the
file shows up later.

Action Comics 2011 is the prove case: the folder must be
`Action Comics (2011)` or Kapowarr will not match year-less New 52
filenames. Files titled `Chapter 1` are force-matched to the leading
issue number (31–34), not issue 1.

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/run-library-imports.sh
```

## Check visibility without SSH

```bash
bash scripts/comics-visibility.sh
```

That replays the last saved snapshot.
