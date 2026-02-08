#!/usr/bin/env bash
# ============================================================================
#  Neurolous Open Source Agent — Cross-Platform Installer
#  Supports: macOS (Intel & Apple Silicon) and Linux/Windows (via Git Bash/WSL)
# ============================================================================

set -e

# --- Colors ----------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Helpers ---------------------------------------------------------------
info()    { echo -e "${CYAN}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()    { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

separator() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# --- Detect OS -------------------------------------------------------------
detect_os() {
    case "$(uname -s)" in
        Darwin*)  OS="mac";;
        Linux*)
            if grep -qEi "(Microsoft|WSL)" /proc/version 2>/dev/null; then
                OS="wsl"
            else
                OS="linux"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)  OS="windows";;
        *)        fail "Unsupported operating system: $(uname -s)";;
    esac
}

detect_arch() {
    ARCH="$(uname -m)"
}

# --- Banner ----------------------------------------------------------------
banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "  _   _                      _                  "
    echo " | \ | | ___ _   _ _ __ ___ | | ___  _   _ ___ "
    echo " |  \| |/ _ \ | | | '__/ _ \| |/ _ \| | | / __|"
    echo " | |\  |  __/ |_| | | | (_) | | (_) | |_| \__ \\"
    echo " |_| \_|\___|\__,_|_|  \___/|_|\___/ \__,_|___/"
    echo ""
    echo -e "${NC}${BOLD}  Open Source Agent — Installer${NC}"
    echo ""
}

# --- Detect platform info --------------------------------------------------
print_system_info() {
    detect_os
    detect_arch

    info "Detected OS:           ${BOLD}${OS}${NC}"
    info "Detected Architecture: ${BOLD}${ARCH}${NC}"
    separator
}

# --- Check / Install Python ------------------------------------------------
ensure_python() {
    info "Checking for Python 3.10+ ..."

    # Find a working python3 command
    PYTHON_CMD=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            PY_VER=$("$cmd" --version 2>&1 | awk '{print $2}')
            PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
            PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
            if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    done

    if [ -n "$PYTHON_CMD" ]; then
        success "Python found: $($PYTHON_CMD --version)"
    else
        warn "Python 3.10+ not found. Attempting to install..."
        case "$OS" in
            mac)
                if command -v brew &>/dev/null; then
                    brew install python@3.12
                else
                    fail "Homebrew not found. Install Homebrew first: https://brew.sh\n       Then re-run this script."
                fi
                ;;
            linux|wsl)
                if command -v apt-get &>/dev/null; then
                    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
                elif command -v dnf &>/dev/null; then
                    sudo dnf install -y python3 python3-pip
                elif command -v pacman &>/dev/null; then
                    sudo pacman -Sy --noconfirm python python-pip
                else
                    fail "Could not detect package manager. Install Python 3.10+ manually."
                fi
                ;;
            windows)
                fail "Install Python 3.10+ from https://www.python.org/downloads/ and re-run."
                ;;
        esac
        # Re-detect
        for cmd in python3 python; do
            if command -v "$cmd" &>/dev/null; then
                PYTHON_CMD="$cmd"
                break
            fi
        done
        [ -z "$PYTHON_CMD" ] && fail "Python installation failed."
        success "Python installed: $($PYTHON_CMD --version)"
    fi
}

# --- Check / Install Ollama ------------------------------------------------
ensure_ollama() {
    info "Checking for Ollama ..."

    if command -v ollama &>/dev/null; then
        success "Ollama found: $(ollama --version 2>/dev/null || echo 'installed')"
    else
        warn "Ollama not found. Attempting to install..."
        case "$OS" in
            mac)
                if command -v brew &>/dev/null; then
                    brew install ollama
                else
                    info "Downloading Ollama for macOS..."
                    curl -fsSL https://ollama.ai/install.sh | sh
                fi
                ;;
            linux|wsl)
                info "Downloading Ollama for Linux..."
                curl -fsSL https://ollama.ai/install.sh | sh
                ;;
            windows)
                fail "Install Ollama from https://ollama.ai/download and re-run."
                ;;
        esac
        command -v ollama &>/dev/null || fail "Ollama installation failed."
        success "Ollama installed."
    fi
}

# --- Start Ollama if not running -------------------------------------------
start_ollama() {
    info "Ensuring Ollama is running..."

    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        success "Ollama is already running."
    else
        info "Starting Ollama in the background..."
        ollama serve &>/dev/null &
        OLLAMA_PID=$!

        # Wait up to 15 seconds for Ollama to become responsive
        for i in $(seq 1 15); do
            if curl -sf http://localhost:11434/api/tags &>/dev/null; then
                success "Ollama is running (PID $OLLAMA_PID)."
                return
            fi
            sleep 1
        done
        fail "Ollama did not start within 15 seconds. Try running 'ollama serve' manually."
    fi
}

# --- Pull Ollama models ----------------------------------------------------
pull_models() {
    info "Checking required Ollama models..."

    MODELS=("gemma3:4b-it-qat" "nomic-embed-text")
    for model in "${MODELS[@]}"; do
        if ollama list 2>/dev/null | grep -q "$(echo "$model" | cut -d: -f1)"; then
            success "Model already pulled: $model"
        else
            info "Pulling model: $model (this may take a few minutes)..."
            ollama pull "$model"
            success "Model pulled: $model"
        fi
    done
}

# --- Set up Python virtual environment & install deps ----------------------
setup_backend() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$SCRIPT_DIR/backend"

    if [ ! -d "$BACKEND_DIR" ]; then
        fail "Backend directory not found at $BACKEND_DIR"
    fi

    info "Setting up Python virtual environment..."

    VENV_DIR="$BACKEND_DIR/venv"
    if [ ! -d "$VENV_DIR" ]; then
        $PYTHON_CMD -m venv "$VENV_DIR"
        success "Virtual environment created."
    else
        success "Virtual environment already exists."
    fi

    # Activate venv
    if [ "$OS" = "windows" ]; then
        source "$VENV_DIR/Scripts/activate"
    else
        source "$VENV_DIR/bin/activate"
    fi

    info "Installing Python dependencies (this may take several minutes on first run)..."
    pip install --upgrade pip --quiet
    pip install -r "$BACKEND_DIR/requirements.txt" --quiet
    success "All Python dependencies installed."
}

# --- Create example config if missing --------------------------------------
ensure_config() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CONFIG_FILE="$SCRIPT_DIR/backend/config/persona.json"
    EXAMPLE_FILE="$SCRIPT_DIR/backend/config/persona.example.json"

    if [ ! -f "$CONFIG_FILE" ]; then
        if [ -f "$EXAMPLE_FILE" ]; then
            cp "$EXAMPLE_FILE" "$CONFIG_FILE"
            info "Created persona.json from example template."
            info "Edit it at: $CONFIG_FILE"
        else
            warn "No persona.json found. Configure via Admin panel at http://localhost:8000/admin"
        fi
    else
        success "Persona config found."
    fi
}

# --- Launch backend and open browser ---------------------------------------
launch() {
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    BACKEND_DIR="$SCRIPT_DIR/backend"

    separator
    echo -e "${GREEN}${BOLD}  Setup complete! Launching Neurolous...${NC}"
    separator

    info "Starting FastAPI backend on http://localhost:8000 ..."
    info "Press Ctrl+C to stop the server."
    echo ""

    # Open browser after a short delay
    (
        sleep 3
        case "$OS" in
            mac)       open "http://localhost:8000" ;;
            linux)     xdg-open "http://localhost:8000" 2>/dev/null || info "Open http://localhost:8000 in your browser." ;;
            wsl)       cmd.exe /c start "http://localhost:8000" 2>/dev/null || powershell.exe Start-Process "http://localhost:8000" 2>/dev/null || info "Open http://localhost:8000 in your browser." ;;
            windows)   start "http://localhost:8000" 2>/dev/null || info "Open http://localhost:8000 in your browser." ;;
        esac
    ) &

    cd "$BACKEND_DIR"
    $PYTHON_CMD main.py
}

# --- Main ------------------------------------------------------------------
main() {
    banner
    print_system_info

    ensure_python
    separator

    ensure_ollama
    separator

    start_ollama
    pull_models
    separator

    setup_backend
    separator

    ensure_config
    launch
}

main "$@"
