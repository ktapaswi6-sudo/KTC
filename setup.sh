#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if ! command -v ffmpeg >/dev/null 2>&1; then echo "Install FFmpeg first: macOS brew install ffmpeg; Debian/Ubuntu sudo apt install ffmpeg"; exit 1; fi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p cache exports fonts music sfx
python -m webbrowser http://127.0.0.1:8000 >/dev/null 2>&1 &
python -m uvicorn app:app --host 127.0.0.1 --port 8000
