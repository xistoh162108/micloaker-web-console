#!/bin/bash
set -e
cd "$(dirname "$0")"
.venv/bin/python helper_control.py status || python3 helper_control.py status
echo
read -r -p "Press Enter to close..."
