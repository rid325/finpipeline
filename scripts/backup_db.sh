#!/usr/bin/env bash
set -euo pipefail

database_url="${MIGRATION_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ -z "$database_url" ]]; then
  echo "Set MIGRATION_DATABASE_URL (preferred) or DATABASE_URL." >&2
  exit 1
fi

backup_file="${1:-finpipeline-$(date -u +%Y%m%dT%H%M%SZ).dump}"
pg_dump --format=custom --no-owner --no-privileges \
  --dbname "$database_url" --file "$backup_file"
echo "Backup written to $backup_file"
