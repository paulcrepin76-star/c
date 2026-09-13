#!/usr/bin/env bash
# Run on Unraid as root. Points Kavita at the comic folders that are
# actually meant to be read. Does not move or rename archives.
# Manga is already a Kavita library. Do not add /books/comics as one root
# (that would pull in .comicarr-scan and every imprint).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CATALOG="${KAVITA_LIBRARIES_JSON:-$HERE/kavita-libraries.json}"
DB=/mnt/user/appdata/kavita/kavita.db
BASE="${KAVITA_URL:-http://127.0.0.1:5001}"

if [ ! -d /mnt/user ]; then
  echo "Run this on Unraid (root@lerouxfamily), not on the Mac."
  exit 1
fi
if [ ! -f "$CATALOG" ]; then
  echo "Missing $CATALOG"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required."
  exit 1
fi
if ! docker inspect kavita >/dev/null 2>&1; then
  echo "kavita container is not installed."
  exit 1
fi
if [ ! -f "$DB" ]; then
  echo "Kavita database not found at $DB"
  exit 1
fi

docker start kavita >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
  if curl -sS -m 2 -o /dev/null -w "%{http_code}" "$BASE/" | grep -qE '200|302'; then
    break
  fi
  sleep 1
done

KEY="$(sqlite3 "$DB" "SELECT Key FROM AppUserAuthKey WHERE Name='opds' LIMIT 1;")"
if [ -z "$KEY" ]; then
  echo "No Kavita OPDS auth key. In Kavita: User Settings → Manage Auth Keys."
  exit 1
fi

AUTH_JSON="$(mktemp)"
LIBS_JSON="$(mktemp)"
trap 'rm -f "$AUTH_JSON" "$LIBS_JSON"' EXIT

if ! curl -sS -m 20 -X POST \
  --get \
  --data-urlencode "apiKey=${KEY}" \
  --data-urlencode "pluginName=resto-kavita-setup" \
  -o "$AUTH_JSON" \
  "$BASE/api/Plugin/authenticate"; then
  echo "Could not reach Kavita at $BASE"
  exit 1
fi

TOKEN="$(jq -r '.token // empty' "$AUTH_JSON")"
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "Kavita plugin authenticate did not return a token."
  exit 1
fi

api() {
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -m 30 -X "$method" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      -d "$body" \
      "$BASE$path"
  else
    curl -sS -m 30 -X "$method" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Accept: application/json" \
      "$BASE$path"
  fi
}

api GET "/api/Library/libraries" > "$LIBS_JSON"

HOST_ROOT="$(jq -r '.host_books_root' "$CATALOG")"
FILE_TYPES="$(jq -c '.file_group_types' "$CATALOG")"
EXCLUDES="$(jq -c '.exclude_patterns' "$CATALOG")"
METADATA_PROVIDER="$(jq -r '.metadata_provider' "$CATALOG")"
CREATED=0
SCAN_IDS=()
SCAN_NAMES=()

while IFS=$'\t' read -r name folder type; do
  host_folder="${folder/#\/books/$HOST_ROOT}"
  if [ ! -d "$host_folder" ]; then
    echo "skip missing folder: $name ($host_folder)"
    continue
  fi
  exists="$(jq -r --arg n "$name" '[.[] | select(.name == $n)] | length' "$LIBS_JSON")"
  if [ "$exists" != "0" ]; then
    id="$(jq -r --arg n "$name" '.[] | select(.name == $n) | .id' "$LIBS_JSON")"
    echo "exists: $name id=$id"
    last="$(sqlite3 "$DB" "SELECT LastScanned FROM Library WHERE Id=$id;")"
    if [ "$last" = "0001-01-01 00:00:00" ] || [ -z "$last" ]; then
      SCAN_IDS+=("$id")
      SCAN_NAMES+=("$name")
    fi
    continue
  fi

  payload="$(jq -nc \
    --arg name "$name" \
    --arg folder "$folder" \
    --argjson type "$type" \
    --argjson fileGroupTypes "$FILE_TYPES" \
    --argjson excludePatterns "$EXCLUDES" \
    --argjson metadataProvider "$METADATA_PROVIDER" \
    '{
      id: 0,
      name: $name,
      type: $type,
      folders: [$folder],
      folderWatching: true,
      includeInDashboard: true,
      includeInSearch: true,
      manageCollections: false,
      manageReadingLists: false,
      allowScrobbling: false,
      allowMetadataMatching: false,
      enableMetadata: false,
      removePrefixForSortName: false,
      inheritWebLinksFromFirstChapter: false,
      defaultLanguage: "",
      metadataProvider: $metadataProvider,
      fileGroupTypes: $fileGroupTypes,
      excludePatterns: $excludePatterns
    }')"

  created="$(api POST "/api/Library/create" "$payload")"
  id="$(echo "$created" | jq -r '.id // empty')"
  if [ -z "$id" ]; then
    echo "create failed: $name"
    echo "$created" | jq -c 'del(.token,.refreshToken)' 2>/dev/null || echo "$created" | head -c 300
    echo
    exit 1
  fi
  echo "created: $name id=$id"
  CREATED=$((CREATED + 1))
  SCAN_IDS+=("$id")
  SCAN_NAMES+=("$name")
done < <(jq -r '.libraries[] | [.name, .folder, (.type|tostring)] | @tsv' "$CATALOG")

api GET "/api/Library/libraries" > "$LIBS_JSON"
echo
echo "Kavita libraries:"
jq -r '.[] | "  \(.id)\t\(.name)\t\(.type)\t\(.folders | join(", "))"' "$LIBS_JSON"

# Kavita drops overlapping scans (or defers them for hours). Wait for each.
for idx in "${!SCAN_IDS[@]}"; do
  id="${SCAN_IDS[$idx]}"
  name="${SCAN_NAMES[$idx]}"
  echo "scan library $id ($name)"
  api POST "/api/Library/scan?libraryId=${id}&force=true" >/dev/null || true
  scanned=""
  for _ in $(seq 1 240); do
    scanned="$(sqlite3 "$DB" "SELECT LastScanned FROM Library WHERE Id=$id;")"
    if [ -n "$scanned" ] && [ "$scanned" != "0001-01-01 00:00:00" ]; then
      series="$(sqlite3 "$DB" "SELECT COUNT(*) FROM Series WHERE LibraryId=$id;")"
      echo "  finished $name lastScanned=$scanned series=$series"
      break
    fi
    sleep 5
  done
  if [ -z "$scanned" ] || [ "$scanned" = "0001-01-01 00:00:00" ]; then
    echo "  still scanning $name; check Kavita later"
  fi
done

echo
echo "Created $CREATED new libraries."
echo "Open http://100.116.48.120:5001 and read from those tiles."
echo "Files were not moved. Leave Kapowarr Import and Rename off. Do not use Rensaio Rename."
