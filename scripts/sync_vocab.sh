#!/usr/bin/env bash
# Non-destructive bidirectional sync of vocabulary_word_definitions and word audio.
#
# - Definitions: inserts docs whose (word, student_level) pair is missing on the
#   destination side. Existing docs are never overwritten.
# - Audio: downloads word_*.wav files that are missing locally (pull) or missing
#   on the remote app (push — not yet supported, audio is generated on-demand).
#
# Usage:
#   scripts/sync_vocab.sh pull                          # prod → local
#   scripts/sync_vocab.sh push                          # local → prod
#   scripts/sync_vocab.sh pull --skip-audio             # definitions only
#   scripts/sync_vocab.sh pull --skip-db                # audio only
#   scripts/sync_vocab.sh pull --app-url https://...    # override prod URL
#
# Environment:
#   PROD_APP_URL   Prod app base URL (for audio pull)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env.scripts"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: $ENV_FILE not found. Copy .env.scripts.example and fill in values." >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

PROD_DB="${PROD_DB:?PROD_DB not set in .env.scripts}"
LOCAL_DB="${LOCAL_DB:?LOCAL_DB not set in .env.scripts}"
PROD_APP_URL="${PROD_APP_URL:-}"
PROD_STATIC_DIR="${PROD_STATIC_DIR:-/app/static}"
LOCAL_STATIC_DIR="${LOCAL_STATIC_DIR:-$(cd "$(dirname "$0")/../src/maestro/static" && pwd)}"

PROD_AUDIO_DIR="${PROD_STATIC_DIR}/audio"
LOCAL_AUDIO_DIR="${LOCAL_STATIC_DIR}/audio"

DIRECTION="pull"
SKIP_AUDIO=false
SKIP_DB=false
FROM=""
TO=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        pull)         DIRECTION="pull"; shift ;;
        push)         DIRECTION="push"; shift ;;
        --skip-audio) SKIP_AUDIO=true; shift ;;
        --skip-db)    SKIP_DB=true; shift ;;
        --from)       FROM="$2"; shift 2 ;;
        --to)         TO="$2"; shift 2 ;;
        --app-url)    PROD_APP_URL="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ "$DIRECTION" == "pull" ]]; then
    FROM="${FROM:-$PROD_DB}"
    TO="${TO:-$LOCAL_DB}"
else
    FROM="${FROM:-$LOCAL_DB}"
    TO="${TO:-$PROD_DB}"
fi

# --- Definitions: non-destructive merge ---
if [[ "$SKIP_DB" == false ]]; then
    echo "==> Syncing vocabulary_word_definitions ($DIRECTION)..."

    mongosh --quiet --eval '
        const src = connect(process.argv[1]);
        const dst = connect(process.argv[2]);

        // Index destination docs by (word, student_level)
        const dstDocs = new Map();
        dst.getCollection("vocabulary_word_definitions").find(
            {}, { word: 1, student_level: 1, updated_at: 1, created_at: 1 }
        ).forEach(d => {
            const key = d.word.toString() + "|" + d.student_level;
            dstDocs.set(key, d);
        });

        // Use updated_at if available, fall back to created_at
        function ts(doc) { return doc.updated_at || doc.created_at; }

        let added = 0, updated = 0, skipped = 0;
        src.getCollection("vocabulary_word_definitions").find().forEach(doc => {
            const key = doc.word.toString() + "|" + doc.student_level;
            const existing = dstDocs.get(key);

            if (!existing) {
                // Missing on destination — insert
                const { _id, ...rest } = doc;
                dst.getCollection("vocabulary_word_definitions").insertOne(rest);
                added++;
            } else if (ts(doc) && ts(existing) && ts(doc) > ts(existing)) {
                // Source is newer — replace
                const { _id, ...rest } = doc;
                dst.getCollection("vocabulary_word_definitions").replaceOne(
                    { _id: existing._id }, rest
                );
                updated++;
            } else {
                skipped++;
            }
        });

        print(`    added: ${added}, updated (newer): ${updated}, skipped: ${skipped}`);
    ' "$FROM" "$TO"

    echo "==> Definition sync complete."
fi

# --- Audio: download missing word_*.wav files ---
if [[ "$SKIP_AUDIO" == false ]]; then
    if [[ "$DIRECTION" == "pull" ]]; then
        mkdir -p "$LOCAL_AUDIO_DIR"

        if [[ -z "$PROD_APP_URL" ]]; then
            echo "Error: PROD_APP_URL not set. Pass --app-url or export PROD_APP_URL." >&2
            exit 1
        fi
        PROD_APP_URL="${PROD_APP_URL%/}"

        echo "==> Fetching word audio list from source DB..."
        AUDIO_PATHS=$(mongosh --quiet --eval '
            db.vocabulary_words.find(
                { audio_path: { $ne: null } },
                { audio_path: 1, _id: 0 }
            ).forEach(d => print(d.audio_path))
        ' "$FROM")

        TOTAL=$(echo "$AUDIO_PATHS" | grep -c . || true)
        COUNT=0; SKIPPED=0; FAILED=0

        echo "==> Downloading missing word audio ($TOTAL in source) to $LOCAL_AUDIO_DIR..."
        while IFS= read -r audio_path; do
            [[ -z "$audio_path" ]] && continue
            filename="$(basename "$audio_path")"
            dest="$LOCAL_AUDIO_DIR/$filename"

            if [[ -f "$dest" ]]; then
                ((SKIPPED++))
                continue
            fi

            if curl -fsSL -o "$dest" "$PROD_APP_URL$audio_path" 2>/dev/null; then
                ((COUNT++))
            else
                echo "    WARN: failed to download $filename" >&2
                rm -f "$dest"
                ((FAILED++))
            fi
        done <<< "$AUDIO_PATHS"

        echo "==> Audio: $COUNT downloaded, $SKIPPED existed, $FAILED failed."
    else
        echo "==> Push: audio is generated on-demand in prod — skipping."
    fi
fi

echo "==> Done."
