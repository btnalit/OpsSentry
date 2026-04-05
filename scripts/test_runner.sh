#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
TEST_TARGETS=("$@")

if [ ${#TEST_TARGETS[@]} -eq 0 ]; then
  TEST_TARGETS=("tests")
fi

PYTHON_CMD=()
if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD=(python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD=(python)
elif command -v py >/dev/null 2>&1; then
  PYTHON_CMD=(py -3)
else
  echo "No suitable Python interpreter found (python3/python/py)." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  "${PYTHON_CMD[@]}" -m venv "$VENV_DIR"
fi

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
elif [ -f "$VENV_DIR/Scripts/activate" ]; then
  # shellcheck source=/dev/null
  source "$VENV_DIR/Scripts/activate"
else
  echo "Virtual environment activate script not found in $VENV_DIR." >&2
  exit 1
fi

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT_DIR"
pytest "${TEST_TARGETS[@]}"
