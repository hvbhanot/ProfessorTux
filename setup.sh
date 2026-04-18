#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Professor Tux – one-shot setup for a fresh Ubuntu install
# Usage:  chmod +x setup.sh && ./setup.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
VENV_PY="$ROOT_DIR/$VENV_DIR/bin/python"
DEFAULT_MODEL="qwen3.5:4b"

# ── helpers ──────────────────────────────────────────────────────────
info()  { echo -e "\n\033[1;34m==> $*\033[0m"; }
warn()  { echo -e "\033[1;33m    $*\033[0m"; }
fail()  { echo -e "\033[1;31mError: $*\033[0m" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

# ── 1. System packages ──────────────────────────────────────────────
info "Installing system dependencies"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
  build-essential cmake curl git \
  python3 python3-venv python3-pip \
  ca-certificates

# ── 2. Verify Python ≥ 3.10 ─────────────────────────────────────────
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PYTHON_OK="$("$PYTHON_BIN" -c 'import sys; print("yes" if sys.version_info >= (3, 10) else "no")')"

if [[ "$PYTHON_OK" != "yes" ]]; then
  fail "Python 3.10+ is required. Found $PYTHON_VERSION."
fi
info "Using $PYTHON_BIN ($PYTHON_VERSION)"

# ── 3. Virtual environment & Python deps ─────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating virtual environment at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  info "Reusing existing virtual environment at $VENV_DIR"
fi

info "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip --quiet

info "Installing Python dependencies"
"$VENV_PY" -m pip install -r requirements.txt --quiet

# ── 4. .env file ─────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  info "Creating .env from .env.example"
  cp .env.example .env
else
  info "Keeping existing .env"
fi

# ── 5. Data directories ─────────────────────────────────────────────
info "Creating data directories"
mkdir -p data/uploads data/chromadb data/logs

# ── 6. Install Ollama ────────────────────────────────────────────────
if need_cmd ollama; then
  info "Ollama already installed: $(ollama --version 2>&1 || true)"
else
  info "Installing Ollama"
  curl -fsSL https://ollama.com/install.sh | sh
fi

# ── 7. Start Ollama & pull the default model ─────────────────────────
info "Ensuring Ollama is running"
if ! pgrep -x ollama >/dev/null 2>&1; then
  ollama serve &>/dev/null &
  OLLAMA_PID=$!
  # wait for the API to become reachable
  for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/ >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf http://127.0.0.1:11434/ >/dev/null 2>&1; then
    warn "Ollama did not start in time — you may need to start it manually."
  fi
fi

info "Pulling default model ($DEFAULT_MODEL) — this may take a while"
ollama pull "$DEFAULT_MODEL" || warn "Model pull failed. Run 'ollama pull $DEFAULT_MODEL' manually."

# ── Done ─────────────────────────────────────────────────────────────
cat <<EOF

$(printf '\033[1;32m')✔ Setup complete.$(printf '\033[0m')

  Start Professor Tux:
    source $VENV_DIR/bin/activate
    python run.py

  Or without activating the venv:
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
