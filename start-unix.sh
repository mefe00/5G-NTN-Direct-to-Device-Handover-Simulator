#!/usr/bin/env bash
# 5G-NTN Disaster Handover Simulator - Linux / macOS Başlatıcı
# Çalıştırmak için: ./start-unix.sh  (gerekirse: chmod +x start-unix.sh)

set -e
cd "$(dirname "$0")"

# Python bul (python3 öncelikli)
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "[HATA] Python bulunamadı."
    echo "Linux:  sudo apt install python3 python3-venv   (Debian/Ubuntu/Mint)"
    echo "        sudo dnf install python3                  (Fedora)"
    echo "macOS:  brew install python3   ya da python.org'dan indirin"
    exit 1
fi

exec "$PY" run.py "$@"
