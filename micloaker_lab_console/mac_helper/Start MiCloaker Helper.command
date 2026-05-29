#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r ../requirements-mac-helper.txt
fi
.venv/bin/python helper_control.py start
echo
echo "MiCloaker Helper started. You may close this window."
read -r -p "Press Enter to close..."
