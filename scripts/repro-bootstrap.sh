#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CMD=${1:-verify}
if [ "$#" -gt 0 ]; then
  shift
fi

case "$CMD" in
  verify)
    if [ -x "$ROOT/.venv/bin/python" ]; then
      PYTHON="$ROOT/.venv/bin/python"
    else
      PYTHON="${PYTHON:-python3}"
    fi
    ;;
  bootstrap|plan)
    PYTHON="${PYTHON:-python3}"
    ;;
  *)
    echo "usage: $0 {bootstrap|verify|plan} [options]" >&2
    exit 64
    ;;
esac

exec "$PYTHON" "$ROOT/tools/repro_bootstrap.py" "$CMD" "$@"
