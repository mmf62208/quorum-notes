"""Localhost-only HTTP server. No cloud unless the user opts into SpaceXAI."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import ai, backup, config, settings as app_settings, vault
from .minutes import Meeting, Motion, Report, email_payload, render_minutes


def _json(handler: BaseHTTPRequestHandler, code: int, payload) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _bytes(handler: BaseHTTPRequestHandler, code: int, data: bytes, content_type: str) -> None:
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or "0")
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length") or "0")
    return handler.rfile.read(length) if length else b""


class Handler(BaseHTTPRequestHandler):
    server_version = "QuorumNotes/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[quorum] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/health":
                return _json(self, 200, {"ok": True, "app": config.APP_NAME, "bind": f"{config.HOST}:{config.PORT}"})
            if path == "/api/status":
                return _json(
                    self,
                    200,
                    {
                        "app": config.APP_NAME,
                        "vault": str(config.vault_dir()),
                        "ai": ai.ai_status(),
                        "settings": app_settings.load_settings(),
                    },
                )
            if path == "/api/settings":
                return _json(self, 200, {"settings": app_settings.load_settings()})
            if path == "/api/meetings":
                return _json(self, 200, {"meetings": vault.list_meetings()})
            if path.startswith("/api/meetings/") and path.endswith("/audio"):
                meeting_id = path.split("/")[3]
                audio = vault.audio_path(meeting_id)
                if not audio.is_file():
                    return _json(self, 404, {"error": "no audio"})
                return _bytes(self, 200, audio.read_bytes(), "audio/wav")
            if path.startswith("/api/meetings/") and path.endswith("/minutes"):
                meeting_id = path.split("/")[3]
                meeting = vault.load_meeting(meeting_id)
                return _json(self, 200, {"markdown": render_minutes(meeting)})
            if path.startswith("/api/meetings/") and path.endswith("/email"):
                meeting_id = path.split("/")[3]
                meeting = vault.load_meeting(meeting_id)
                return _json(self, 200, email_payload(meeting))
            if path.startswith("/api/meetings/") and "/api/meetings/" == path[:14] and path.count("/") == 3:
                meeting_id = path.rsplit("/", 1)[-1]
                meeting = vault.load_meeting(meeting_id)
                return _json(self, 200, {"meeting": meeting.to_dict(), "markdown": render_minutes(meeting)})
            if path == "/api/backups":
                return _json(self, 200, {"backups": backup.list_backups()})
            return self._static(path)
        except FileNotFoundError:
            _json(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            _json(self, 400, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/settings":
                return _json(self, 200, {"settings": app_settings.save_settings(_read_json(self))})
            if path == "/api/meetings":
                meeting = vault.create_meeting(_read_json(self))
                return _json(self, 201, {"meeting": meeting.to_dict(), "markdown": render_minutes(meeting)})
            if path.startswith("/api/meetings/") and path.endswith("/audio"):
                meeting_id = path.split("/")[3]
                data = _read_body(self)
                if not data:
                    return _json(self, 400, {"error": "empty audio"})
                vault.save_audio(meeting_id, data)
                return _json(self, 200, {"ok": True, "bytes": len(data)})
            if path.startswith("/api/meetings/") and path.endswith("/transcribe"):
                meeting_id = path.split("/")[3]
                audio = vault.audio_path(meeting_id)
                if not audio.is_file():
                    return _json(self, 400, {"error": "record WAV first"})
                text = ai.transcribe_wav(audio)
                vault.save_transcript(meeting_id, text)
                return _json(self, 200, {"transcript": text})
            if path.startswith("/api/meetings/") and path.endswith("/draft"):
                meeting_id = path.split("/")[3]
                meeting = vault.load_meeting(meeting_id)
                text = ai.draft_minutes(meeting, vault.read_transcript(meeting_id))
                return _json(self, 200, {"markdown": text})
            if path == "/api/backup":
                dest = backup.make_backup()
                return _json(self, 201, {"ok": True, "path": str(dest), "name": dest.name})
            _json(self, 404, {"error": "not found"})
        except FileNotFoundError:
            _json(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            _json(self, 400, {"error": str(exc)})

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/meetings/") and path.count("/") == 3:
                meeting_id = path.rsplit("/", 1)[-1]
                existing = vault.load_meeting(meeting_id)
                incoming = _read_json(self)
                incoming["id"] = existing.id
                incoming.setdefault("created_at", existing.created_at)
                meeting = Meeting.from_dict({**existing.to_dict(), **incoming, "id": existing.id})
                # Re-wrap nested types after merge
                meeting.reports = [r if isinstance(r, Report) else Report(**r) for r in meeting.reports]
                meeting.new_business = [
                    m if isinstance(m, Motion) else Motion(**m) for m in meeting.new_business
                ]
                vault.save_meeting(meeting)
                return _json(self, 200, {"meeting": meeting.to_dict(), "markdown": render_minutes(meeting)})
            _json(self, 404, {"error": "not found"})
        except FileNotFoundError:
            _json(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            _json(self, 400, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/meetings/") and path.count("/") == 3:
                vault.delete_meeting(path.rsplit("/", 1)[-1])
                return _json(self, 200, {"ok": True})
            _json(self, 404, {"error": "not found"})
        except FileNotFoundError:
            _json(self, 404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            _json(self, 400, {"error": str(exc)})

    def _static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        rel = path.lstrip("/")
        dest = (config.web_dir() / rel).resolve()
        root = config.web_dir().resolve()
        if root not in dest.parents and dest != root:
            return _json(self, 403, {"error": "forbidden"})
        if not dest.is_file():
            return _json(self, 404, {"error": "not found"})
        extra = {".webmanifest": "application/manifest+json", ".js": "text/javascript"}
        ctype = extra.get(dest.suffix) or mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
        _bytes(self, 200, dest.read_bytes(), ctype)


def serve() -> None:
    vault.ensure_vault()
    httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print(f"{config.APP_NAME} at http://{config.HOST}:{config.PORT}")
    print(f"Vault: {config.vault_dir()}")
    print("AI is off until XAI_API_KEY is set and you click an opt-in action.")
    httpd.serve_forever()
