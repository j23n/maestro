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
#   scripts/sync_vocab.sh pull --staging                # staging → local
#   scripts/sync_vocab.sh push                          # local → prod
#   scripts/sync_vocab.sh push --staging                # local → staging
#   scripts/sync_vocab.sh pull --skip-audio             # definitions only
#   scripts/sync_vocab.sh pull --skip-db                # audio only
#
# Exit codes:
#   0  success
#   1  configuration / argument error
#   2  DB sync failed
#   3  audio sync had failures

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env.scripts"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.scripts.example and fill in values." >&2
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

PROD_DB="${PROD_DB:?PROD_DB not set in .env.scripts}"
STAGING_DB="${STAGING_DB:?STAGING_DB not set in .env.scripts}"
LOCAL_DB="${LOCAL_DB:?LOCAL_DB not set in .env.scripts}"
PROD_APP_URL="${PROD_APP_URL:-}"
STAGING_APP_URL="${STAGING_APP_URL:-}"
LOCAL_STATIC_DIR="${LOCAL_STATIC_DIR:-$(cd "$(dirname "$0")/../src/maestro/static" && pwd)}"

LOCAL_AUDIO_DIR="${LOCAL_STATIC_DIR}/audio"

DIRECTION="pull"
USE_STAGING=false
SKIP_AUDIO=false
SKIP_DB=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        pull)         DIRECTION="pull"; shift ;;
        push)         DIRECTION="push"; shift ;;
        --staging)    USE_STAGING=true; shift ;;
        --skip-audio) SKIP_AUDIO=true; shift ;;
        --skip-db)    SKIP_DB=true; shift ;;
        *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if [[ "$USE_STAGING" == true ]]; then
    REMOTE_DB="$STAGING_DB"
    REMOTE_APP_URL="$STAGING_APP_URL"
    REMOTE_NAME="staging"
else
    REMOTE_DB="$PROD_DB"
    REMOTE_APP_URL="$PROD_APP_URL"
    REMOTE_NAME="prod"
fi

if [[ "$DIRECTION" == "pull" ]]; then
    FROM="$REMOTE_DB"
    TO="$LOCAL_DB"
else
    FROM="$LOCAL_DB"
    TO="$REMOTE_DB"
fi

# Mask credentials in log output
log_uri() { echo "$1" | sed -E 's|://[^@]+@|://***@|'; }
echo "==> Direction: $DIRECTION ($REMOTE_NAME ↔ local)"
echo "    FROM: $(log_uri "$FROM")"
echo "    TO:   $(log_uri "$TO")"

# --- Definitions: non-destructive merge ---
if [[ "$SKIP_DB" == false ]]; then
    echo ""
    echo "==> Syncing vocabulary_word_definitions..."

    echo "    Connecting to source and destination databases..."
    SYNC_OUTPUT=$(SRC_URI="$FROM" DST_URI="$TO" mongosh --quiet --nodb --eval '
        const src = connect(process.env.SRC_URI);
        const dst = connect(process.env.DST_URI);

        // Build word ID → word string lookups for both sides
        function buildWordLookup(db) {
            const m = new Map();
            db.getCollection("vocabulary_words").find({}, { word: 1 }).forEach(d => {
                m.set(d._id.toString(), d.word);
            });
            return m;
        }
        const srcWords = buildWordLookup(src);
        const dstWords = buildWordLookup(dst);
        print("    Source vocabulary_words: " + srcWords.size);
        print("    Destination vocabulary_words: " + dstWords.size);

        const srcCount = src.getCollection("vocabulary_word_definitions").countDocuments();
        print("    Source definitions: " + srcCount);

        // Index destination defs by (word_string, student_level)
        const dstDocs = new Map();
        dst.getCollection("vocabulary_word_definitions").find(
            {}, { word: 1, student_level: 1, updated_at: 1, created_at: 1 }
        ).forEach(d => {
            const wordId = (d.word.oid || d.word.$id || d.word).toString();
            const wordStr = dstWords.get(wordId);
            if (wordStr) {
                const key = wordStr + "|" + d.student_level;
                dstDocs.set(key, d);
            }
        });
        print("    Destination definitions: " + dstDocs.size);

        // Reverse lookup: word string → destination ObjectId
        const dstWordsByName = new Map();
        for (const [id, w] of dstWords) dstWordsByName.set(w, id);

        // Use updated_at if available, fall back to created_at
        function ts(doc) { return doc.updated_at || doc.created_at; }

        let added = 0, updated = 0, skipped = 0, errors = 0;
        src.getCollection("vocabulary_word_definitions").find().forEach(doc => {
            const wordId = (doc.word.oid || doc.word.$id || doc.word).toString();
            const wordStr = srcWords.get(wordId);
            if (!wordStr) { skipped++; return; }
            const key = wordStr + "|" + doc.student_level;
            const existing = dstDocs.get(key);

            try {
                if (!existing) {
                    // Find the matching word ID on the destination side
                    const dstId = dstWordsByName.get(wordStr);
                    if (!dstId) {
                        skipped++;  // word does not exist on destination
                    } else {
                        const { _id, ...rest } = doc;
                        rest.word = DBRef("vocabulary_words", ObjectId(dstId));
                        dst.getCollection("vocabulary_word_definitions").insertOne(rest);
                        added++;
                    }
                } else if (ts(doc) && ts(existing) && ts(doc) > ts(existing)) {
                    const { _id, ...rest } = doc;
                    dst.getCollection("vocabulary_word_definitions").replaceOne(
                        { _id: existing._id }, rest
                    );
                    updated++;
                } else {
                    skipped++;
                }
            } catch (e) {
                print("    ERROR: failed to sync " + key + ": " + e.message);
                errors++;
            }
        });

        print("    Result: added=" + added + " updated=" + updated + " skipped=" + skipped + " errors=" + errors);
        if (errors > 0) quit(1);
    ' 2>&1) || {
        echo "$SYNC_OUTPUT"
        echo "ERROR: DB sync failed." >&2
        exit 2
    }
    echo "$SYNC_OUTPUT"
    echo "==> Definition sync complete."
else
    echo "==> Skipping DB sync (--skip-db)."
fi

# --- Audio: download missing word_*.wav files ---
if [[ "$SKIP_AUDIO" == false ]]; then
    if [[ "$DIRECTION" == "pull" ]]; then
        if [[ -z "$REMOTE_APP_URL" ]]; then
            echo "ERROR: ${REMOTE_NAME^^}_APP_URL not set in .env.scripts." >&2
            exit 1
        fi
        REMOTE_APP_URL="${REMOTE_APP_URL%/}"

        echo ""
        echo "==> Audio: downloading to $LOCAL_AUDIO_DIR"
        mkdir -p "$LOCAL_AUDIO_DIR"

        echo "    Fetching words with definitions from source DB..."
        AUDIO_PATHS=$(mongosh --quiet "$FROM" --eval '
            function slugify(text) {
                return text.toLowerCase()
                    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                    .replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
            }
            // Get word IDs that have definitions (these are the ones with audio)
            const wordIds = new Set();
            db.vocabulary_word_definitions.find({}, { word: 1 }).forEach(d => {
                const id = d.word.oid || d.word.$id || d.word;
                wordIds.add(id.toString());
            });
            const paths = [];
            db.vocabulary_words.find({}, { word: 1 }).forEach(d => {
                if (wordIds.has(d._id.toString())) {
                    paths.push("/static/audio/word_" + slugify(d.word) + ".wav");
                }
            });
            print("    Words with definitions (may have audio): " + paths.length);
            paths.forEach(p => print(p));
        ' 2>&1) || {
            echo "ERROR: Failed to query audio paths from source DB." >&2
            echo "$AUDIO_PATHS" >&2
            exit 2
        }

        # First line is the count log, rest are paths
        echo "$AUDIO_PATHS" | head -1
        AUDIO_PATHS=$(echo "$AUDIO_PATHS" | tail -n +2)

        TOTAL=$(echo "$AUDIO_PATHS" | grep -c . || true)
        COUNT=0; SKIPPED=0; FAILED=0

        echo "    Downloading $TOTAL audio files..."
        while IFS= read -r audio_path; do
            [[ -z "$audio_path" ]] && continue
            filename="$(basename "$audio_path")"
            dest="$LOCAL_AUDIO_DIR/$filename"

            if [[ -f "$dest" ]]; then
                ((SKIPPED++)) || true
                continue
            fi

            if curl -fsSL -o "$dest" "$REMOTE_APP_URL$audio_path" 2>/dev/null; then
                ((COUNT++)) || true
            else
                echo "    WARN: failed to download $filename from $REMOTE_APP_URL$audio_path" >&2
                rm -f "$dest"
                ((FAILED++)) || true
            fi
        done <<< "$AUDIO_PATHS"

        echo "    Result: downloaded=$COUNT existed=$SKIPPED failed=$FAILED"

        if [[ "$FAILED" -gt 0 && "$COUNT" -eq 0 && "$SKIPPED" -eq 0 ]]; then
            echo "ERROR: all $FAILED audio file(s) failed to download." >&2
            exit 3
        elif [[ "$FAILED" -gt 0 ]]; then
            echo "    NOTE: $FAILED file(s) not found on remote (TTS may not have run yet)."
        fi
        echo "==> Audio sync complete."
    else
        echo "==> Push: audio is generated on-demand in prod — skipping."
    fi
else
    echo "==> Skipping audio sync (--skip-audio)."
fi

echo ""
echo "==> Done."
