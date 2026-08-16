"""Opt-in SpaceXAI helpers. Never called unless the user asks and XAI_API_KEY is set."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from .minutes import Meeting, render_minutes

FORMAL_MINUTES_PROMPT = """You are a formal meeting adjutant.
Turn the provided notes and optional transcript into formal civic/organization minutes.

Required sections, in this order:
- Title + date
- Meeting Called to Order
- Opening Ceremonies (if mentioned)
- Roll Call / Quorum (list names present; state whether a quorum was present)
- Approval of Previous Minutes
- Reports
- Old Business
- New Business (each item as a motion with mover, seconder, and result when known)
- Announcements / Good of the Order
- Adjournment
- Respectfully submitted (use the given officer)

Write in the same formal voice as Sons of the American Legion / civic lodge minutes.
Do not invent attendance, dollar amounts, or vote counts. If unknown, write that it was not recorded.
Return Markdown only.
"""


def ai_status() -> dict[str, bool | str]:
    key = config.xai_api_key()
    return {
        "enabled": bool(key),
        "provider": "SpaceXAI",
        "model": config.xai_model(),
        "base_url": config.xai_base_url(),
    }


def _post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    key = config.xai_api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set. Advanced AI is opt-in only.")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SpaceXAI HTTP {exc.code}: {detail[:500]}") from exc


def _multipart_file(url: str, field: str, filename: str, data: bytes, content_type: str) -> dict:
    key = config.xai_api_key()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set. Advanced AI is opt-in only.")
    boundary = "----QuorumBoundary7MA4YWxkTrZu0gW"
    chunks = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(chunks)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SpaceXAI HTTP {exc.code}: {detail[:500]}") from exc


def transcribe_wav(path: Path) -> str:
    result = _multipart_file(
        f"{config.xai_base_url()}/stt",
        "file",
        path.name,
        path.read_bytes(),
        "audio/wav",
    )
    text = result.get("text") or result.get("transcript") or ""
    if not text and isinstance(result.get("output_text"), str):
        text = result["output_text"]
    if not text:
        raise RuntimeError("SpaceXAI STT returned no text")
    return text.strip()


def _output_text(result: dict) -> str:
    if isinstance(result.get("output_text"), str) and result["output_text"].strip():
        return result["output_text"].strip()
    output = result.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
        if parts:
            return "\n".join(parts).strip()
    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        if isinstance(msg, dict) and msg.get("content"):
            return str(msg["content"]).strip()
    raise RuntimeError("SpaceXAI returned no draft text")


def draft_minutes(meeting: Meeting, transcript: str = "") -> str:
    user = {
        "organization": meeting.organization,
        "title": meeting.title,
        "date": meeting.date,
        "location": meeting.location,
        "called_to_order_by": meeting.called_to_order_by,
        "roster": meeting.roster,
        "present": meeting.present,
        "opening": meeting.opening,
        "reports": [r.__dict__ for r in meeting.reports],
        "old_business": meeting.old_business,
        "new_business": [m.__dict__ for m in meeting.new_business],
        "announcements": meeting.announcements,
        "submitted_by": meeting.submitted_by,
        "submitted_office": meeting.submitted_office,
        "notes": meeting.notes,
        "current_render": render_minutes(meeting),
        "transcript": transcript,
    }
    result = _post_json(
        f"{config.xai_base_url()}/responses",
        {
            "model": config.xai_model(),
            "input": [
                {"role": "system", "content": FORMAL_MINUTES_PROMPT},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
        },
    )
    return _output_text(result)
