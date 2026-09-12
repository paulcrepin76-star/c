# Comics and manga on Unraid

Kapowarr and Comicarr do not browse the disk the way Kavita does. They only
keep series that match ComicVine (Kapowarr) or ComicVine / MangaDex (Comicarr).
The files live under imprint folders (`DC Comics`, `dc rebirth`, `Shueisha`),
so a first-level scan of `/comics` or `/manga` sees publishers, not series.

## What is on the box

| Host path | Container path | App |
| --- | --- | --- |
| `/mnt/user/media/book/comics` | `/comics` | Comicarr, Kapowarr |
| `/mnt/user/media/book/manga` | `/manga` | Comicarr, Kapowarr, Kavita |
| `/mnt/user/media/book` | `/books` | Kavita |
| `/mnt/user/omnibus-data` | `/data` on Omnibus | Empty placeholder. Do not use. |

Kavita (`http://100.116.48.120:5001`) is the reader. Comicarr is
`http://100.116.48.120:8090`. Kapowarr is `http://100.116.48.120:5656`.

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

ComicVine is rate-limited. Hundreds of series take a while. Unmatched rows
stay unmatched: French/Spanish editions, dump folders, and most manga will
not become Kapowarr volumes.

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
