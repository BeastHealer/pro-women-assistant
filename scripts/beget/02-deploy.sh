#!/usr/bin/env bash
# Build & start production stack on Beget VPS.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${ROOT}"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.production.example → .env and fill secrets"
  exit 1
fi

if [[ ! -d ../tg_vk_parser ]]; then
  echo "Expected sibling ../tg_vk_parser (SQLite + photos). Abort."
  exit 1
fi

# Replace YOUR_DOMAIN in nginx config if DOMAIN is set
if [[ -n "${DOMAIN:-}" ]]; then
  sed -i.bak "s/YOUR_DOMAIN/${DOMAIN}/g" nginx/nginx.prod.conf
  echo "Patched nginx.nginx.prod.conf for DOMAIN=${DOMAIN}"
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile with-nginx pull || true
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile with-nginx up -d --build

echo
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile with-nginx ps
echo
echo "Health (via localhost):"
curl -fsS http://127.0.0.1:8080/health || true
echo
curl -fsS http://127.0.0.1:8000/health || true
echo
curl -fsS http://127.0.0.1:5678/healthz || true
echo
echo "Optional CLIP archive index (long):"
echo "  curl -X POST 'http://127.0.0.1:8000/admin/rebuild-index?batch_size=4'"
