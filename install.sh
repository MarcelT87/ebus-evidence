#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

PYTHON_BIN=${PYTHON:-python3}
VENV_DIR=".venv"

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'     >/dev/null 2>&1
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN was not found" >&2
  exit 2
fi

if ! python_supported "$PYTHON_BIN"; then
  echo "error: Python 3.11 or newer is required" >&2
  "$PYTHON_BIN" --version >&2 || true
  exit 2
fi

if [ -L "$VENV_DIR" ]; then
  echo "error: $VENV_DIR is a symbolic link; refusing to modify it" >&2
  echo "move or remove that link, then run: bash install.sh" >&2
  exit 2
fi

if [ -e "$VENV_DIR" ] && [ ! -d "$VENV_DIR" ]; then
  echo "error: $VENV_DIR exists but is not a directory" >&2
  echo "move or remove it, then run: bash install.sh" >&2
  exit 2
fi

if [ -d "$VENV_DIR" ]; then
  if [ ! -f "$VENV_DIR/pyvenv.cfg" ]; then
    echo "error: $VENV_DIR exists but does not look like a Python virtual environment" >&2
    echo "move or remove that directory, then run: bash install.sh" >&2
    echo "no files were removed" >&2
    exit 2
  fi

  if (
    [ ! -x "$VENV_DIR/bin/python" ] ||
    ! python_supported "$VENV_DIR/bin/python" ||
    ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1
  ); then
    echo "Existing .venv is unusable or uses an unsupported Python."
    echo "Recreating the local virtual environment..."
    rm -rf "$VENV_DIR"
  else
    echo "Using existing virtual environment."
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "error: virtual environment creation did not provide $VENV_DIR/bin/python" >&2
  echo "check that Python virtual-environment support is installed, then rerun install.sh" >&2
  exit 2
fi

if ! python_supported "$VENV_DIR/bin/python"; then
  echo "error: virtual environment Python is older than 3.11" >&2
  "$VENV_DIR/bin/python" --version >&2 || true
  echo "remove $VENV_DIR and rerun: bash install.sh" >&2
  exit 2
fi

if ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  echo "error: pip is not available inside $VENV_DIR" >&2
  echo "remove $VENV_DIR and rerun: bash install.sh" >&2
  exit 2
fi

echo "Installing ebus-evidence..."
"$VENV_DIR/bin/python" -m pip install -e .

cat > evidence <<'EOF'
#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN="$ROOT/.venv/bin/ebus-evidence"

if [ ! -x "$BIN" ]; then
  echo "error: ebus-evidence is not installed in $ROOT/.venv" >&2
  echo "run: bash install.sh" >&2
  exit 2
fi

cd "$ROOT"
exec "$BIN" "$@"
EOF
chmod +x evidence

echo
echo "Installation complete."
echo
echo "Next:"
echo "  ./evidence doctor"
