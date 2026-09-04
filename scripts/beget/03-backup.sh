#!/usr/bin/env bash
# Backup SQLite parser DB + n8n workflows.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_ROOT="${BACKUP_DIR:-${HOME}/backups}"
DATE="$(date +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_ROOT}"

DB="${ROOT}/../tg_vk_parser/data/images.db"
if [[ -f "${DB}" ]]; then
  cp -a "${DB}" "${BACKUP_ROOT}/images_${DATE}.db"
  echo "Saved ${BACKUP_ROOT}/images_${DATE}.db"
fi

if docker ps --format '{{.Names}}' | grep -qx 'pro-women-n8n'; then
  docker exec pro-women-n8n n8n export:workflow --all --pretty \
    > "${BACKUP_ROOT}/n8n_workflows_${DATE}.json" || true
  echo "Saved ${BACKUP_ROOT}/n8n_workflows_${DATE}.json"
fi

# Keep 30 days
find "${BACKUP_ROOT}" -name 'images_*.db' -mtime +30 -delete 2>/dev/null || true
find "${BACKUP_ROOT}" -name 'n8n_workflows_*.json' -mtime +30 -delete 2>/dev/null || true
echo "Backup done: ${DATE}"
