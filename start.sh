#!/bin/sh
# Startet ERG-Training. Legt beim ersten Start eine virtuelle Python-Umgebung an.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python training.py "$@"
