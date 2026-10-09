#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Missing project environment. Follow the setup commands in README.md." >&2
  exit 1
fi
exec .venv/bin/python server.py "$@"
