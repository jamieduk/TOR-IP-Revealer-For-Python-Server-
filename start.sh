#!/bin/bash
# (c) J~Net 2026
#
# ./start.sh

LOG_FILE="log.txt"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Virtual Environment Created."
fi

if [ -z "$VIRTUAL_ENV" ] || [ "$(basename "$VIRTUAL_ENV")" != "venv" ]; then
    source venv/bin/activate
    echo "Virtual Environment Activated."
else
    echo "Virtual Environment already active."
fi

touch "$LOG_FILE"
python reveal-ip.py --host :: --port 9192 >> "$LOG_FILE"
cat "$LOG_FILE"
