#!/usr/bin/env bash
set -euo pipefail

N8N_API_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJiN2U5YmI5OC1jYmQ0LTQ1MGUtOWE4Yy1iNjEzNjc1M2MwNmEiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiYWM2ZDRmNTYtNTFjNy00OTI3LTk0MWEtOGNmNGQ4ZGU0YTI1IiwiaWF0IjoxNzg5ODMzMzQwfQ.zx3JdVm6t0ofH7hlwnhJLGw2ylhOUtQkKeQ89qw7SW8"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <execution-id>" >&2
  exit 1
fi

if [[ -z "${N8N_API_KEY:-}" ]]; then
  echo "Error: N8N_API_KEY is not set" >&2
  exit 1
fi

EXEC_ID="$1"
OUT_FILE="n8n-execution-${EXEC_ID}.json"

curl -sS -H "X-N8N-API-KEY: $N8N_API_KEY" \
  "http://localhost:5678/api/v1/executions?limit=100&includeData=true" \
  | jq --arg id "$EXEC_ID" '.data[] | select((.id|tostring) == $id)' \
  > "$OUT_FILE"

if [[ ! -s "$OUT_FILE" ]]; then
  echo "Error: execution $EXEC_ID not found (or empty response)" >&2
  rm -f "$OUT_FILE"
  exit 1
fi

ABS_PATH="$(realpath "$OUT_FILE")"
if command -v wslpath >/dev/null 2>&1; then
  WIN_PATH="$(wslpath -w "$ABS_PATH")"
  echo "Saved execution $EXEC_ID to $WIN_PATH"
else
  echo "Saved execution $EXEC_ID to $ABS_PATH"
fi
