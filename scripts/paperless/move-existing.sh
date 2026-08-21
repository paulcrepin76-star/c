#!/usr/bin/env bash
# Assign existing Gmail invoices to Survey Cafe Archive.
# Run on Unraid: ./scripts/paperless/move-existing.sh
set -euo pipefail

C="$(
  docker ps --format '{{.Names}}|{{.Image}}' |
  awk -F'|' 'tolower($2) ~ /paperless/ {print $1; exit}'
)"

if [[ -z "${C:-}" ]]; then
  echo "ERROR: Paperless container not found."
  docker ps --format 'table {{.Names}}\t{{.Image}}'
  exit 1
fi

M="$(
  docker exec "$C" sh -lc \
  'find /usr/src/paperless /app -maxdepth 4 -name manage.py -print -quit 2>/dev/null'
)"

if [[ -z "${M:-}" ]]; then
  echo "ERROR: manage.py not found in $C"
  exit 1
fi

echo "Using Paperless container: $C"
echo "Organizing existing Gmail documents into Survey Cafe Archive ..."

docker exec -i "$C" python3 "$M" shell <<'PY'
from documents.models import Document, StoragePath, Tag
from paperless_mail.models import MailRule

rule = MailRule.objects.filter(name="Import Gmail PDF invoices").select_related("account", "owner").first()
if rule is None:
    raise SystemExit("ERROR: Gmail mail rule was not found.")

owner = rule.owner or rule.account.owner
storage_template = (
    "Survey Cafe/{{ created_year }}/{{ correspondent }}/"
    "{{ document_type }}/{{ created }} - {{ title }} - {{ doc_pk }}"
)

storage_path = StoragePath.objects.filter(name__iexact="Survey Cafe Archive", owner=owner).first()
if storage_path is None:
    storage_path = StoragePath.objects.create(
        name="Survey Cafe Archive",
        owner=owner,
        path=storage_template,
        match="",
        matching_algorithm=StoragePath.MATCH_NONE,
        is_insensitive=True,
    )
else:
    storage_path.path = storage_template
    storage_path.save(update_fields=["path"])

gmail_tag = Tag.objects.filter(name__iexact="Imported - Gmail").first()
needs_review = Tag.objects.filter(name__iexact="Needs Review").first()

documents = Document.objects.all()
if gmail_tag:
    documents = documents.filter(tags=gmail_tag).distinct()

total = documents.count()
print(f"Organizing {total} document(s)...")

for number, document in enumerate(documents.iterator(chunk_size=50), start=1):
    changed = False
    if document.storage_path_id != storage_path.id:
        document.storage_path = storage_path
        document.save(update_fields=["storage_path"])
        changed = True
    if needs_review and not document.tags.filter(pk=needs_review.pk).exists():
        document.tags.add(needs_review)
        changed = True
    if number % 25 == 0 or number == total:
        print(f"Processed {number}/{total} changed={changed}")

print("Done.")
print(f"Storage template: {storage_template}")
PY
