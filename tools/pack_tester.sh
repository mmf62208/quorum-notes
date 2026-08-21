#!/bin/sh
# Build a zip another tester can unpack and run (desktop).
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:-"$ROOT/dist/quorum-tester.zip"}
mkdir -p "$(dirname "$OUT")"
python3 - "$ROOT" "$OUT" <<'ENDPACK'
import sys, time, zipfile
from pathlib import Path

root, dest = Path(sys.argv[1]), Path(sys.argv[2])
top = "quorum-notes"
include_files = [
    "LICENSE",
    "README.md",
    "START_HERE.txt",
]
include_folders = ("quorum", "docs", "tools")
exec_suffixes = {".sh", ".command"}

def add_file(zf, path, arcname):
    data = path.read_bytes()
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.date_time = time.localtime(path.stat().st_mtime)[:6]
    mode = 0o100755 if path.suffix in exec_suffixes else 0o100644
    info.external_attr = mode << 16
    zf.writestr(info, data)

with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in include_files:
        path = root / rel
        if path.is_file():
            add_file(zf, path, f"{top}/{rel}")
    for folder in include_folders:
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            add_file(zf, path, f"{top}/{path.relative_to(root).as_posix()}")
    launchers = (
        ("tools/start-quorum.sh", "Start Quorum.sh"),
        ("tools/Start-Quorum.command", "Start Quorum.command"),
        ("tools/Start-Quorum.bat", "Start Quorum.bat"),
    )
    for src, dest_name in launchers:
        path = root / src
        if path.is_file():
            add_file(zf, path, f"{top}/{dest_name}")
print(dest)
ENDPACK
