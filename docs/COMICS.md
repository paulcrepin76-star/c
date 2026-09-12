# Comics and manga on Unraid

Kapowarr does not show the whole collection because it is not looking at the same folders Komga reads, and it is not a folder browser.

## What is going on

The files live here:

| Host path | What it is |
| --- | --- |
| `/mnt/user/media/book/manga` | Unified manga (Suwayomi / Tranga → Komga) |
| `/mnt/user/media/book/comics` | Western comics (Omnibus Downloads, and the Kapowarr root) |
| `/mnt/user/omnibus-data` | Empty placeholder. Do not point anything here. |
| `/mnt/user/media/animation serie/Bleach/Bleach/Manga` | Old Bleach mount. Leave it. |

Omnibus already mounts the real library at **`/books`** (`/mnt/user/media/book`) and the empty share at **`/data`**. If a library or Smart Match path is `/data/manga` or `/data/comics`, the UI is empty and Smart Match returns `Unauthorized path access`.

Kapowarr, if it is running, only sees **one container root** (usually `/comics`). That should map to `/mnt/user/media/book/comics`. It will never list the manga tree. ComicVine also will not match most Suwayomi / Tranga files or BD française.

Last time this box was inspected there was **no `kapowarr` container**. The apps that already see files are Komga, Suwayomi, Tranga, and Omnibus.

## Why Library Import looks small

Kapowarr [only imports files in a subfolder of a root](https://casvt.github.io/Kapowarr/general_info/implementation_details/). It then keeps ComicVine matches and drops the rest. These all hide issues:

- Root folder typed as `/mnt/user/media/book/comics` instead of `/comics`
- "Only match English volumes"
- A low "Max folders scanned"
- ComicVine rate limit mid-import (unmatched rows are skipped even if checked)
- Files named like manga chapters, not ComicVine issues

Use **Import**. Do not use **Import and Rename** on a folder Komga already reads. Rename moves files into Kapowarr's volume folders.

## Check it again on the server

```bash
ssh root@100.116.48.120
cd /mnt/user/appdata/resto
git pull
bash scripts/comics-visibility.sh
```

From this repo without SSH:

```bash
bash scripts/comics-visibility.sh
```

That replays the last saved snapshot.

## If you want Kapowarr for GetComics only

```bash
mkdir -p /mnt/user/appdata/kapowarr/{db,temp}
docker compose -f /mnt/user/appdata/resto/docker/comics/compose.kapowarr.yml up -d
```

Open `http://100.116.48.120:5656`, add a ComicVine key, add root folder **`/comics`**, then Library Import. Leave manga on Komga.
