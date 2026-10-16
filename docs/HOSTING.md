# Free hosting layout

FinPipeline uses three independent free services:

1. **Neon Postgres** stores durable data. Use the pooled connection string as `DATABASE_URL` and the direct connection string as `MIGRATION_DATABASE_URL`. Keep the TLS parameters Neon supplies.
2. **GitHub Actions** runs ingestion even while the Render service sleeps. Add both URLs as repository Actions secrets; `FRED_API_KEY` is optional.
3. **Render** serves the API and dashboard. Set both database URLs, `SECRET_KEY`, and `ENABLE_APSCHEDULER=false`.

## Move the current database to Neon

```bash
MIGRATION_DATABASE_URL="$OLD_DIRECT_URL" ./scripts/backup_db.sh current.dump
MIGRATION_DATABASE_URL="$NEON_DIRECT_URL" ./scripts/restore_db.sh current.dump
MIGRATION_DATABASE_URL="$NEON_DIRECT_URL" poetry run alembic -c finpipeline/alembic.ini upgrade head
```

The restore script does not remove existing objects unless `RESTORE_CLEAN=1` is explicitly set. Verify row counts through `/metrics` before changing Render's `DATABASE_URL`.

## Scheduled workflow inactivity

GitHub can disable scheduled workflows in a public repository after 60 days without repository activity. Scheduled executions should not be assumed to reset that timer. Keep the workflows on the default branch, use their manual-dispatch buttons for recovery, and set an external reminder before day 60 to check that both schedules remain enabled.
