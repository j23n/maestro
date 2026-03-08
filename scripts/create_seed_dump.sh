#!/usr/bin/env bash
# Regenerate the seed dump from the local MongoDB container.
# Writes to data/seed/current/ (used by the app on startup).
set -euo pipefail

DEST="data/seed/current"
CONTAINER="maestro-db-1"

COLLECTIONS=(
  comm_functions
  curriculum_scenarios
  drill_templates
  grammar_points
  grammar_point_explanations
  vocabulary_words
  vocabulary_word_definitions
)

# Get credentials from the running container
USER=$(docker exec "$CONTAINER" printenv MONGODB_INITDB_ROOT_USERNAME)
PASS=$(docker exec "$CONTAINER" printenv MONGODB_INITDB_ROOT_PASSWORD)

# Dump each collection
for col in "${COLLECTIONS[@]}"; do
  docker exec "$CONTAINER" mongodump \
    --db maestro \
    --username "$USER" --password "$PASS" --authenticationDatabase admin \
    --collection "$col" \
    --out /tmp/seed_dump 2>&1
done

# Copy to local
rm -rf "$DEST"
mkdir -p "$DEST"
docker cp "${CONTAINER}:/tmp/seed_dump/maestro/." "$DEST/"
docker exec "$CONTAINER" rm -rf /tmp/seed_dump

echo "Seed dump created at ${DEST}/"
ls -lh "$DEST/"
