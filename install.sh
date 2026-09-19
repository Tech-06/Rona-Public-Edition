#!/usr/bin/env bash
# Bootstrap installer for Rona (macOS/Linux). The only job of this script
# is to make sure a Python 3.11+ interpreter is on PATH -- installing one
# via brew/apt/dnf/pacman if it's missing or too old -- then it hands off
# to the real installer, which is written in Python (installer/main.py).
# See that file (and installer/*.py) for component selection, venvs, .env
# generation, and the web dashboard's npm build.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

version_ge_3_11() {
    local ver="$1" major minor
    major="$(echo "$ver" | cut -d. -f1)"
    minor="$(echo "$ver" | cut -d. -f2)"
    if [ "$major" -gt 3 ]; then
        return 0
    fi
    [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]
}

find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local ver
            ver="$("$cmd" --version 2>&1 | awk '{print $2}')"
            if version_ge_3_11 "$ver"; then
                command -v "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"

# Shown in both languages -- the installer hasn't had a chance to ask which
# one yet (that question, and everything after it, is Python's job).
if [ -z "$PYTHON" ]; then
    echo "Python 3.11+ not found. / Python 3.11 ya da üstü bulunamadı."
    OS_NAME="$(uname -s)"
    INSTALL_CMD=""
    if [ "$OS_NAME" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
        INSTALL_CMD="brew install python@3.12"
    elif command -v apt-get >/dev/null 2>&1; then
        INSTALL_CMD="sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv"
    elif command -v dnf >/dev/null 2>&1; then
        INSTALL_CMD="sudo dnf install -y python3.12"
    elif command -v pacman >/dev/null 2>&1; then
        INSTALL_CMD="sudo pacman -S --noconfirm python"
    else
        echo "No supported package manager found. Install Python 3.11+ and run the script again."
        echo "Desteklenen bir paket yöneticisi bulunamadı. Python 3.11+ kurup scripti tekrar çalıştır."
        exit 1
    fi
    echo "This command will run: $INSTALL_CMD"
    echo "Şu komut çalıştırılacak: $INSTALL_CMD"
    read -r -p "Continue? / Onaylıyor musun? [y/e, N/H] " answer
    case "$answer" in
        [yYeE]*) eval "$INSTALL_CMD" ;;
        *) echo "Cancelled. / Vazgeçildi."; exit 1 ;;
    esac
    PYTHON="$(find_python || true)"
    if [ -z "$PYTHON" ]; then
        echo "Python was installed but not found on PATH. Open a new terminal and try again."
        echo "Python kuruldu ama PATH'te bulunamadı. Yeni bir terminal açıp tekrar dene."
        exit 1
    fi
fi

exec "$PYTHON" "$REPO_ROOT/installer/main.py" "$@"
