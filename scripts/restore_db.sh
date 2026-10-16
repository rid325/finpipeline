#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: MIGRATION_DATABASE_URL=... $0 path/to/backup.dump" >&2
  exit 1
fi

database_url="${MIGRATION_DATABASE_URL:-${DATABASE_URL:-}}"
if [[ -z "$database_url" ]]; then
  echo "Set MIGRATION_DATABASE_URL (preferred) or DATABASE_URL." >&2
  exit 1
fi

backup_file="$1"
if [[ ! -f "$backup_file" ]]; then
  echo "Backup not found: $backup_file" >&2
  exit 1
fi

restore_options=(--no-owner --no-privileges --exit-on-error)
if [[ "${RESTORE_CLEAN:-0}" == "1" ]]; then
  restore_options+=(--clean --if-exists)
fi
pg_restore "${restore_options[@]}" --dbname "$database_url" "$backup_file"
echo "Restore completed from $backup_file"
