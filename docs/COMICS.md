# Comics and manga on Unraid

Kavita reads the folders on disk. Rensaio grabs **manga**. Kapowarr grabs
**comics**. Do not turn on Rensaio **Rename** or Kapowarr **Import and
Rename** on a folder Kavita already reads.

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

Rensaio uses Mihon extensions (not Prowlarr / qBittorrent). The install
script turns on English/French search, shows NSFW so MPD Psycho is visible,
skips the import wizard (that can rewrite Kavita folders), and installs
MangaDex, MangaFire, MANGA Plus, and Weeb Central. Search those five titles
in the UI and subscribe. New chapters land under `/mnt/user/media/book/manga`.

If Rensaio is recreated:

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
bash scripts/rensaio-install.sh
bash scripts/rensaio-search.sh
```

Comicarr was removed. Its appdata is kept as
`/mnt/user/appdata/comicarr-backup-*` for rollback. Manga files were not
deleted.

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
an hour. Use **Import**. Do not use **Import and Rename**.

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
