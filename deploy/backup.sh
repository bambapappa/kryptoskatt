#!/usr/bin/env bash
# Nightly PostgreSQL backup with rotation. Run from cron as the deploy user:
#   15 3 * * * /opt/kryptoskatt/deploy/backup.sh >> /var/log/kryptoskatt-backup.log 2>&1
# Backups contain users' personal data: keep them encrypted/permission-restricted
# and no longer than BACKUP_KEEP_DAYS (deleted accounts disappear from backups
# once they rotate out, which the privacy policy relies on).
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-/var/backups/kryptoskatt}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
# shellcheck disable=SC1091
set -a; . ./.env; set +a

umask 077
mkdir -p "$BACKUP_DIR"
file="$BACKUP_DIR/kryptoskatt-$(date +%Y%m%d-%H%M%S).sql.gz"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-kryptoskatt}" "${POSTGRES_DB:-kryptoskatt}" | gzip > "$file"
echo "$(date -Is) backup written: $file"
find "$BACKUP_DIR" -name 'kryptoskatt-*.sql.gz' -mtime +"$BACKUP_KEEP_DAYS" -delete
