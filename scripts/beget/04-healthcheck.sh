#!/usr/bin/env bash
# Local health checks (services bound to 127.0.0.1 in prod).
set -euo pipefail

check() {
  local name="$1" url="$2"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${url}" || echo 000)"
  if [[ "${code}" == "200" ]]; then
    echo "OK  ${name} (${code})"
  else
    echo "FAIL ${name} (${code}) ${url}"
    return 1
  fi
}

fail=0
check "assistant" "http://127.0.0.1:8080/health" || fail=1
check "parser" "http://127.0.0.1:8001/health" || fail=1
check "n8n" "http://127.0.0.1:5678/healthz" || fail=1
exit "${fail}"
