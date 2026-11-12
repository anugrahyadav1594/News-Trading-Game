#!/bin/sh
set -eu

mkdir -p /backups
INTERVAL="${BACKUP_INTERVAL_SEC:-900}"
RETENTION="${BACKUP_RETENTION_COUNT:-24}"

echo "[mtt-backup] Starting automated PostgreSQL backup daemon (interval=${INTERVAL}s, retention=${RETENTION})"

while true; do
  TS="$(date -u +%Y%m%dT%H%M%SZ)"
  TARGET="/backups/mtt_exchange_${TS}.sql.gz"
  echo "[mtt-backup] Creating snapshot ${TARGET}..."
  pg_dump --format=plain --no-owner --no-privileges | gzip -9 > "${TARGET}"
  echo "[mtt-backup] Snapshot complete ($(du -h "${TARGET}" | cut -f1))"

  # Rotate older backups beyond retention count
  ls -1t /backups/mtt_exchange_*.sql.gz 2>/dev/null | tail -n +"$((RETENTION + 1))" | xargs -r rm -f
  sleep "${INTERVAL}"
done
