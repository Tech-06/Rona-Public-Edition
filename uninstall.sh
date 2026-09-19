#!/usr/bin/env bash
# Bootstrap uninstaller for Rona (macOS/Linux). Mirrors install.sh's own
# bootstrap: find a Python 3.11+ interpreter, then hand off to the real
# uninstaller (installer/uninstall.py). Unlike install.sh, this never
# offers to *install* Python -- installing an interpreter just to remove
# Rona would be backwards; if none is found, it says so and stops.
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

# Shown in both languages -- the uninstaller hasn't had a chance to ask
# which one yet (that question is Python's job, same as install.sh).
if [ -z "$PYTHON" ]; then
    echo "Python 3.11+ not found, needed to run the uninstaller. / Kaldırma aracını çalıştırmak için Python 3.11 ya da üstü gerekli, bulunamadı."
    echo "Install Python 3.11+ from https://python.org and run this script again. / https://python.org adresinden Python 3.11+ kur ve bu scripti tekrar çalıştır."
    exit 1
fi

exec "$PYTHON" "$REPO_ROOT/installer/uninstall.py" "$@"
