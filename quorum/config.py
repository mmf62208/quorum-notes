"""Paths and bind address. Everything stays on this machine by default."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Quorum Notes"
HOST = os.environ.get("QUORUM_HOST", "127.0.0.1")
PORT = int(os.environ.get("QUORUM_PORT", "4840"))

ROOT = Path(__file__).resolve().parent.parent


def vault_dir() -> Path:
    override = os.environ.get("QUORUM_VAULT")
    if override:
        return Path(override).expanduser().resolve()
    return (ROOT / "vault").resolve()


def backups_dir() -> Path:
    override = os.environ.get("QUORUM_BACKUPS")
    if override:
        return Path(override).expanduser().resolve()
    return (ROOT / "backups").resolve()


def web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def xai_api_key() -> str | None:
    key = os.environ.get("XAI_API_KEY", "").strip()
    return key or None


def xai_base_url() -> str:
    return os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")


def xai_model() -> str:
    return os.environ.get("XAI_MODEL", "grok-4.6")
