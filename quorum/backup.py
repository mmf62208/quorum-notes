"""Local zip backups of the vault. Nothing is uploaded."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .config import backups_dir, vault_dir


def make_backup() -> Path:
    src = vault_dir()
    dest_dir = backups_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = dest_dir / f"quorum-vault-{stamp}.zip"
    with ZipFile(dest, "w", compression=ZIP_DEFLATED) as zf:
        if src.exists():
            for path in src.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(src).as_posix())
        zf.writestr("BACKUP.txt", f"Quorum Notes local vault backup {stamp}\n")
    return dest


def list_backups() -> list[dict[str, str | int]]:
    dest_dir = backups_dir()
    if not dest_dir.exists():
        return []
    items = []
    for path in sorted(dest_dir.glob("quorum-vault-*.zip"), reverse=True):
        items.append({"name": path.name, "size": path.stat().st_size, "path": str(path)})
    return items
