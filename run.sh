#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -x "$here/venv/bin/python" ]]; then
  python_bin="$here/venv/bin/python"
else
  python_bin="${PYTHON:-python3}"
fi

exec "$python_bin" -X utf8 "$here/scripts/icc_search.py" "$@"
