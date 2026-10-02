#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

PYTHON_BIN=${PYTHON:-python3}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN was not found" >&2
  exit 2
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "error: Python 3.11 or newer is required" >&2
  "$PYTHON_BIN" --version >&2 || true
  exit 2
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Installing ebus-evidence..."
.venv/bin/python -m pip install -e .

chmod +x evidence

echo
echo "Installation complete."
echo
echo "Next:"
echo "  ./evidence doctor"
