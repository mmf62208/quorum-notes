#!/bin/sh
# Double-click on a Mac to start Quorum without typing python3 -m.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -d "$HERE/quorum" ]; then
  ROOT="$HERE"
elif [ -d "$HERE/../quorum" ]; then
  ROOT=$(CDPATH= cd -- "$HERE/.." && pwd)
else
  echo "Could not find the Quorum folder. Unzip again so Start Quorum sits next to the quorum folder."
  exit 1
fi

cd "$ROOT"
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
  PY=python3
elif command -v python >/dev/null 2>&1 && python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
  PY=python
elif command -v py >/dev/null 2>&1 && py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
  PY="py -3"
else
  echo "Quorum needs Python 3.11 or newer. Install Python from python.org, then double-click Start Quorum again."
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  (sleep 1; open "http://127.0.0.1:4840") >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
  (sleep 1; xdg-open "http://127.0.0.1:4840") >/dev/null 2>&1 &
fi

if [ "$PY" = "py -3" ]; then
  exec py -3 -m quorum
fi
exec "$PY" -m quorum
