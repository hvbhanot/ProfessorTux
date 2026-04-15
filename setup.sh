#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
VENV_PY="$ROOT_DIR/$VENV_DIR/bin/python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Error: $PYTHON_BIN is not installed or not on PATH." >&2
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PYTHON_OK="$("$PYTHON_BIN" -c 'import sys; print("yes" if sys.version_info >= (3, 10) else "no")')"

if [[ "$PYTHON_OK" != "yes" ]]; then
  echo "Error: Python 3.10+ is required. Found $PYTHON_VERSION." >&2
  exit 1
fi

echo "==> Using $PYTHON_BIN ($PYTHON_VERSION)"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  echo "==> Reusing existing virtual environment at $VENV_DIR"
fi

echo "==> Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip

echo "==> Installing Python dependencies"
"$VENV_PY" -m pip install -r requirements.txt

if [[ ! -f ".env" ]]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
else
  echo "==> Keeping existing .env"
fi

echo "==> Creating data directories"
mkdir -p data/uploads data/chromadb data/logs

if command -v ollama >/dev/null 2>&1; then
  echo "==> Ollama detected: $(command -v ollama)"
else
  echo "==> Ollama not found on PATH"
  echo "    Install it from https://ollama.com if you want local or cloud-backed generation."
fi

cat <<EOF

Setup complete.

Next steps:
  1. Start Ollama:
       ollama serve

  2. Make sure a model exists:
       ollama pull qwen3.5:4b

  3. Start Professor Tux:
       source $VENV_DIR/bin/activate
       python run.py

     or without activating:
       $VENV_PY run.py

Access points after launch:
  Student UI:  http://localhost:8000/
  Admin UI:    http://localhost:8000/admin
  Docs:        http://localhost:8000/docs
  API Docs:    http://localhost:8000/api/docs

Default admin credentials:
  username: admin
  password: professortux

EOF
