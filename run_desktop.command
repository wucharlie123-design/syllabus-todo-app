#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
if [[ -x "$HOME/Documents/event-assistant-ai/.venv/bin/python" ]]; then
    exec "$HOME/Documents/event-assistant-ai/.venv/bin/python" main_ui.py
else
    exec python3 main_ui.py
fi
