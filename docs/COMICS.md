# Comics and manga on Unraid

Kavita reads the folders on disk. Rensaio grabs **manga**. Kapowarr and
Mylar3 grab **comics**. Do not turn on Rensaio **Rename**, Kapowarr
**Import and Rename**, or Mylar3 **Manage / Import / Rename** on a
folder Kavita already reads.

## What is on the box

| Role | App | URL |
| --- | --- | --- |
| Read | Kavita | `http://100.116.48.120:5001` |
| Manga grabs | Rensaio | `http://100.116.48.120:9833` |
| Comic grabs | Kapowarr | `http://100.116.48.120:5656` |
| Comic grabs | Mylar3 | `http://100.116.48.120:8090` |

| Host path | Container path | App |
| --- | --- | --- |
| `/mnt/user/media/book/comics` | `/comics` | Kapowarr, Mylar3 |
| `/mnt/user/media/book/manga` | `/series` | Rensaio |
| `/mnt/user/media/book/manga` | `/manga` | Kavita |
| `/mnt/user/media/book` | `/books` | Kavita |

Rensaio uses Mihon extensions (not Prowlarr / qBittorrent). The install
script turns on English/French search, shows NSFW so MPD Psycho is visible,
skips the import wizard (that can rewrite Kavita folders), and installs
MangaDex, MangaFire, MANGA Plus, Weeb Central, plus official English
publishers (VIZ, Webtoons, Kodansha, Manga UP!, INKR, Tapas). Search those
five titles in the UI and subscribe. New chapters land under
`/mnt/user/media/book/manga`.

If Rensaio is recreated:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/rensaio-install.sh
bash scripts/rensaio-search.sh
```

Comicarr was removed. Its appdata is kept as
`/mnt/user/appdata/comicarr-backup-*` for rollback. Manga files were not
deleted. Port `8090` is Mylar3 now.

## Mylar3 comics

Mylar3 sits next to Kapowarr. It does not replace it. Both see
`/mnt/user/media/book/comics` as `/comics`. Mylar3 has its own download
folder (`/mnt/user/downloads/mylar3`). It is on `media-net` so it can
reach Prowlarr later. The install copies Kapowarr's ComicVine key and
leaves **Rename**, **Enforce Permissions**, and **Import** off. It does
not scan or import the existing library.

The leftover June appdata at `/mnt/user/appdata/mylar3` is reused. Do
not add `/comics/DC New 52` or `/comics/dc rebirth` as extra roots.

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/mylar3-install.sh
bash scripts/mylar3-import.sh
```

The import script scans `/comics` in place (`imp_paths=1`), stamps
Kapowarr ComicVine IDs onto folders that have exactly one volume, then
mass-imports. It does not touch manga. Do not send `imp_move=0` to
Mylar — CherryPy treats that string as true and will rename files.
ComicVine is still ~200 requests/hour per key, so a 420 means wait an
hour and run the import again.

Do not turn on Mylar3 **Move Files** or **Rename Files**.

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
