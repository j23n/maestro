#!/usr/bin/env bash
# Copy the prod database to staging (drop & replace).
#
# Usage:
#   scripts/sync_db.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env.scripts"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: $ENV_FILE not found. Copy .env.scripts.example and fill in values." >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

PROD_DB="${PROD_DB:?PROD_DB not set in .env.scripts}"
STAGING_DB="${STAGING_DB:?STAGING_DB not set in .env.scripts}"

ARCHIVE="$(mktemp /tmp/maestro_dump.XXXXXX.archive)"
trap 'rm -f "$ARCHIVE"' EXIT

echo "==> Dumping prod database..."
mongodump --uri="$PROD_DB" --archive="$ARCHIVE"

echo "==> Restoring to staging (drop & replace)..."
mongorestore --uri="$STAGING_DB" --archive="$ARCHIVE" --drop

# --- Verify counts match ---
echo "==> Verifying..."

count_collections() {
    mongosh --quiet --eval '
        const colls = db.getCollectionNames().sort();
        for (const c of colls) print(c + ":" + db.getCollection(c).countDocuments());
    ' "$1"
}

PROD_COUNTS="$(count_collections "$PROD_DB")"
STAGING_COUNTS="$(count_collections "$STAGING_DB")"

MISMATCHES=0
while IFS=: read -r coll prod_count; do
    staging_count=$(echo "$STAGING_COUNTS" | grep "^${coll}:" | cut -d: -f2)
    if [[ "$prod_count" != "$staging_count" ]]; then
        echo "  MISMATCH: $coll — prod=$prod_count staging=${staging_count:-missing}" >&2
        ((MISMATCHES++))
    fi
done <<< "$PROD_COUNTS"

if [[ "$MISMATCHES" -gt 0 ]]; then
    echo "==> FAILED: $MISMATCHES collection(s) differ." >&2
    exit 1
fi

echo "==> OK. All collections match ($(echo "$PROD_COUNTS" | wc -l) collections)."
