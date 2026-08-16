"""Local meeting vault. Audio and JSON never leave this directory unless the user exports."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import vault_dir
from .minutes import Meeting, render_minutes

SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{6,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_vault() -> Path:
    root = vault_dir()
    (root / "meetings").mkdir(parents=True, exist_ok=True)
    return root


def _meeting_dir(meeting_id: str) -> Path:
    if not SAFE_ID.match(meeting_id):
        raise ValueError("invalid meeting id")
    return ensure_vault() / "meetings" / meeting_id


def list_meetings() -> list[dict[str, Any]]:
    root = ensure_vault() / "meetings"
    items: list[dict[str, Any]] = []
    if not root.exists():
        return items
    for path in sorted(root.iterdir(), reverse=True):
        meta = path / "meeting.json"
        if not meta.is_file():
            continue
        data = json.loads(meta.read_text(encoding="utf-8"))
        items.append(
            {
                "id": data.get("id", path.name),
                "title": data.get("title", ""),
                "organization": data.get("organization", ""),
                "date": data.get("date", ""),
                "updated_at": data.get("updated_at", ""),
                "has_audio": (path / "audio.wav").is_file(),
                "has_transcript": (path / "transcript.txt").is_file(),
                "quorum": Meeting.from_dict(data).quorum_present(),
            }
        )
    items.sort(key=lambda m: m.get("updated_at") or m.get("date") or "", reverse=True)
    return items


def create_meeting(fields: dict[str, Any] | None = None) -> Meeting:
    fields = dict(fields or {})
    meeting_id = fields.pop("id", None) or uuid.uuid4().hex[:12]
    now = _now()
    meeting = Meeting.from_dict(
        {
            "id": meeting_id,
            "created_at": now,
            "updated_at": now,
            **fields,
        }
    )
    save_meeting(meeting)
    return meeting


def load_meeting(meeting_id: str) -> Meeting:
    path = _meeting_dir(meeting_id) / "meeting.json"
    if not path.is_file():
        raise FileNotFoundError(meeting_id)
    meeting = Meeting.from_dict(json.loads(path.read_text(encoding="utf-8")))
    meeting.has_audio = (_meeting_dir(meeting_id) / "audio.wav").is_file()
    meeting.has_transcript = (_meeting_dir(meeting_id) / "transcript.txt").is_file()
    return meeting


def save_meeting(meeting: Meeting) -> Meeting:
    folder = _meeting_dir(meeting.id)
    folder.mkdir(parents=True, exist_ok=True)
    meeting.updated_at = _now()
    meeting.has_audio = (folder / "audio.wav").is_file()
    meeting.has_transcript = (folder / "transcript.txt").is_file()
    (folder / "meeting.json").write_text(
        json.dumps(meeting.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (folder / "minutes.md").write_text(render_minutes(meeting), encoding="utf-8")
    if meeting.notes:
        (folder / "notes.md").write_text(meeting.notes, encoding="utf-8")
    return meeting


def save_audio(meeting_id: str, data: bytes) -> Path:
    folder = _meeting_dir(meeting_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "audio.wav"
    dest.write_bytes(data)
    meeting = load_meeting(meeting_id)
    save_meeting(meeting)
    return dest


def audio_path(meeting_id: str) -> Path:
    return _meeting_dir(meeting_id) / "audio.wav"


def save_transcript(meeting_id: str, text: str) -> Path:
    dest = _meeting_dir(meeting_id) / "transcript.txt"
    dest.write_text(text, encoding="utf-8")
    meeting = load_meeting(meeting_id)
    save_meeting(meeting)
    return dest


def read_transcript(meeting_id: str) -> str:
    path = _meeting_dir(meeting_id) / "transcript.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def delete_meeting(meeting_id: str) -> None:
    folder = _meeting_dir(meeting_id)
    if not folder.exists():
        raise FileNotFoundError(meeting_id)
    for child in folder.iterdir():
        if child.is_file():
            child.unlink()
    folder.rmdir()
