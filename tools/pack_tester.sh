#!/bin/sh
# Build a zip another tester can unpack and run (desktop).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-"$ROOT/dist/quorum-tester.zip"}
mkdir -p "$(dirname "$OUT")"
python3 - "$ROOT" "$OUT" <<'PY'
import sys, zipfile
from pathlib import Path
root, dest = Path(sys.argv[1]), Path(sys.argv[2])
include = [
    "LICENSE", "README.md",
]
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in include:
        path = root / rel
        if path.is_file():
            zf.write(path, rel)
    for folder in ("quorum", "tests", "tools"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(root).as_posix())
print(dest)
PY
