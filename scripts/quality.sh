#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${AIVS_PYTHON:-python}"
if [[ -x ".venv/bin/python" && -z "${AIVS_PYTHON:-}" ]]; then
  PYTHON_BIN=".venv/bin/python"
fi

"$PYTHON_BIN" -m compileall -q apps packages providers tests
"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m ruff format --check .
"$PYTHON_BIN" -m pytest
