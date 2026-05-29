#!/bin/bash
set -e
cd "$(dirname "$0")"
.venv/bin/python helper_control.py stop || python3 helper_control.py stop
echo
read -r -p "Press Enter to close..."
