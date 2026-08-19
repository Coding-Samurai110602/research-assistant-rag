#!/usr/bin/env bash
# Initialize the Postgres schema (pgvector extension + tables + indexes).
# Requires docker-compose services to be running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

source "$ROOT_DIR/.env" 2>/dev/null || true

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDB="${POSTGRES_DB:-research_assistant}"
PGUSER="${POSTGRES_USER:-ra_user}"
export PGPASSWORD="${POSTGRES_PASSWORD:-changeme}"

echo "Waiting for Postgres at $PGHOST:$PGPORT..."
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDB" 2>/dev/null; do
  sleep 1
done

echo "Applying schema..."
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDB" \
  -f "$ROOT_DIR/src/research_assistant/db/schema.sql"

echo "Schema applied successfully."
