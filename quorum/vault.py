"""Local meeting vault. Audio and JSON never leave this directory unless the user exports."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import vault_dir
from .minutes import Meeting, enforce_motion_rules, render_minutes
from .naming import meeting_stem
from .retention import should_delete_audio
from .templates import opening_for
from . import settings as app_settings

SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{4,120}$")


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
                "file_stem": data.get("file_stem", path.name),
                "has_audio": (path / "audio.wav").is_file() or any(path.glob("*.wav")),
                "has_transcript": (path / "transcript.txt").is_file(),
                "quorum": Meeting.from_dict(data).quorum_present(),
            }
        )
    items.sort(key=lambda m: m.get("updated_at") or m.get("date") or "", reverse=True)
    return items


def _unique_stem(stem: str) -> str:
    root = ensure_vault() / "meetings"
    if not (root / stem).exists():
        return stem
    for i in range(2, 50):
        candidate = f"{stem}_{i}"
        if not (root / candidate).exists():
            return candidate
    return f"{stem}_{uuid.uuid4().hex[:4]}"


def create_meeting(fields: dict[str, Any] | None = None) -> Meeting:
    fields = dict(fields or {})
    prefs = app_settings.load_settings()
    fields.setdefault("organization", prefs.get("organization", ""))
    fields.setdefault("submitted_by", prefs.get("submitted_by", ""))
    fields.setdefault("submitted_office", prefs.get("submitted_office", ""))
    fields.setdefault("location", prefs.get("default_location", ""))
    fields.setdefault("called_to_order_by", prefs.get("called_to_order_by", ""))
    fields.setdefault("roster", list(prefs.get("roster") or []))
    fields.setdefault("roberts", bool(prefs.get("roberts", True)))
    fields.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
    if "opening" not in fields:
        fields["opening"] = opening_for(str(prefs.get("template") or "sal"))
    stem = fields.get("file_stem") or meeting_stem(
        fields.get("organization", ""),
        fields.get("title", "Regular Meeting"),
    )
    stem = _unique_stem(stem)
    meeting_id = fields.pop("id", None) or stem
    now = _now()
    meeting = Meeting.from_dict(
        {
            "id": meeting_id,
            "file_stem": stem,
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
    folder = _meeting_dir(meeting_id)
    meeting.has_audio = (folder / "audio.wav").is_file() or any(folder.glob("*.wav"))
    meeting.has_transcript = (folder / "transcript.txt").is_file()
    return meeting


def delete_audio_files(meeting_id: str) -> int:
    folder = _meeting_dir(meeting_id)
    if not folder.is_dir():
        return 0
    removed = 0
    for wav in folder.glob("*.wav"):
        wav.unlink()
        removed += 1
    return removed


def apply_retention(meeting: Meeting) -> bool:
    """Delete the tape when the user's retention policy says so. Minutes stay."""
    prefs = app_settings.load_settings()
    policy = str(prefs.get("retention") or "until_approved")
    folder = _meeting_dir(meeting.id)
    wavs = list(folder.glob("*.wav")) if folder.is_dir() else []
    recorded_at = None
    if wavs:
        newest = max(wavs, key=lambda p: p.stat().st_mtime)
        recorded_at = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    if should_delete_audio(
        policy,
        minutes_approved=bool(meeting.minutes_approved),
        recorded_at=recorded_at,
    ):
        delete_audio_files(meeting.id)
        meeting.has_audio = False
        return True
    return False


def save_meeting(meeting: Meeting) -> Meeting:
    enforce_motion_rules(meeting)
    folder = _meeting_dir(meeting.id)
    folder.mkdir(parents=True, exist_ok=True)
    apply_retention(meeting)
    meeting.updated_at = _now()
    meeting.has_audio = any(folder.glob("*.wav"))
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
    meeting = load_meeting(meeting_id)
    dest = folder / f"{meeting.file_stem or meeting_id}.wav"
    dest.write_bytes(data)
    save_meeting(load_meeting(meeting_id))
    return dest


def audio_path(meeting_id: str) -> Path:
    folder = _meeting_dir(meeting_id)
    named = folder / f"{load_meeting(meeting_id).file_stem or meeting_id}.wav"
    if named.is_file():
        return named
    legacy = folder / "audio.wav"
    if legacy.is_file():
        return legacy
    found = sorted(folder.glob("*.wav"))
    return found[0] if found else named


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
