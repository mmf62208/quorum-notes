"""Local bylaws / standing-rules scan. Suggestions only — never auto-applied.

Text PDFs and plain files are read on this device. Images use tesseract only when
that binary is already on PATH. No network, no cloud, no AI.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import settings as app_settings
from .minutes import normalize_doc_label
from .officers import Officer, add_officer_role, officers_to_dicts, resolve_officers
from .quorum_rule import QuorumRule, is_officer_title, normalize_quorum_rule, preview_rule
from .roster import KNOWN_TITLES, display_title, normalize_title

RULES_LABELS = ("bylaws", "standing_rules")

_TEXT_EXT = frozenset({".txt", ".md", ".text", ".csv"})
_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"})

_TITLE_ALT = "|".join(re.escape(title) for title in sorted(KNOWN_TITLES, key=len, reverse=True))
_TITLE_FIND = re.compile(rf"\b({_TITLE_ALT})\b", re.I)
_PDF_STRING = re.compile(rb"\((?:\\.|[^\\)])*\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_PRINTABLE = set(range(32, 127)) | {9, 10, 13}

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_NUMBER_RE = "|".join(list(_NUMBER_WORDS) + [r"\d+"])
_OTHER_OFFICERS_RE = re.compile(
    rf"(?:at\s+least\s+)?({_NUMBER_RE})\s+(?:other\s+)?officers?",
    re.I,
)
_MEMBERS_RE = re.compile(
    rf"(?:at\s+least\s+)?({_NUMBER_RE})\s+members?",
    re.I,
)

_WEAK_TITLE_KEYS = frozenset(
    {
        normalize_title("Finance"),
        normalize_title("Membership"),
        normalize_title("Advocate"),
        normalize_title("Chair"),
    }
)

_CUSTOM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "meeting_day",
        re.compile(r"(?:regular\s+)?meetings?\s+shall\s+be\s+held\b[^.!?\n]*", re.I),
    ),
    (
        "meeting_day",
        re.compile(
            r"\b(?:first|second|third|fourth|last)\s+"
            r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b[^.!?\n]*",
            re.I,
        ),
    ),
    (
        "meeting_time",
        re.compile(r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)\b[^.!?\n]*", re.I),
    ),
    ("order_of_business", re.compile(r"\border of business\b[^.!?\n]*", re.I)),
    ("opening", re.compile(r"\bopening ceremon(?:y|ies)\b[^.!?\n]*", re.I)),
    (
        "opening",
        re.compile(
            r"\b(?:pledge of allegiance|opening prayer|moment of silence|pow/?mia)\b[^.!?\n]*",
            re.I,
        ),
    ),
)

KEEP_FILE_FALLBACK = (
    "The file is kept in the vault. Enter the quorum rule and officers by hand."
)
NO_TEXT_MESSAGE = f"No readable text in this file. {KEEP_FILE_FALLBACK}"
NO_MATCH_MESSAGE = (
    f"No quorum, officer titles, or meeting customs found. {KEEP_FILE_FALLBACK}"
)
OCR_ABSENT_MESSAGE = (
    f"No local OCR tool found (tesseract). {KEEP_FILE_FALLBACK}"
)
SUGGEST_MESSAGE = (
    "Suggestions only. Confirm or edit before they fill the quorum rule or officer roles."
)


def is_rules_label(label: str) -> bool:
    return normalize_doc_label(label) in RULES_LABELS


def _on_path(name: str) -> str | None:
    return shutil.which(name)


def local_tools() -> dict[str, bool]:
    return {"pdftotext": bool(_on_path("pdftotext")), "tesseract": bool(_on_path("tesseract"))}


def _looks_like_text(data: bytes) -> bool:
    if not data or b"\x00" in data[:4096]:
        return False
    sample = data[:4096]
    printable = sum(1 for byte in sample if byte in _PRINTABLE)
    return printable / max(len(sample), 1) >= 0.85


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def _pdf_unescape(raw: bytes) -> str:
    out = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte == 0x5C and index + 1 < len(raw):
            nxt = raw[index + 1]
            mapped = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
            if nxt in mapped:
                out.append(mapped[nxt])
                index += 2
                continue
            if 0x30 <= nxt <= 0x37:
                octal = bytearray()
                look = index + 1
                while look < len(raw) and look < index + 4 and 0x30 <= raw[look] <= 0x37:
                    octal.append(raw[look])
                    look += 1
                out.append(int(octal.decode("ascii"), 8) & 0xFF)
                index = look
                continue
            out.append(nxt)
            index += 2
            continue
        out.append(byte)
        index += 1
    return out.decode("latin-1", errors="replace")


def _pdf_parentheticals(data: bytes) -> str:
    chunks: list[str] = []
    for match in _PDF_STRING.finditer(data or b""):
        text = " ".join(_pdf_unescape(match.group(0)[1:-1]).split())
        letters = sum(ch.isalpha() for ch in text)
        if letters >= 8 and letters / max(len(text), 1) >= 0.35:
            chunks.append(text)
    return "\n".join(chunks)


def _run_cli(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess[bytes] | None:
    if not argv or not _on_path(argv[0]):
        return None
    try:
        return subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _run_pdftotext(data: bytes) -> str:
    if not _on_path("pdftotext"):
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "doc.pdf"
            dest = Path(tmp) / "doc.txt"
            src.write_bytes(data)
            proc = _run_cli(["pdftotext", "-layout", str(src), str(dest)])
            if proc is None:
                return ""
            if dest.is_file():
                return dest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return ""


def _run_tesseract(data: bytes, ext: str) -> str:
    if not _on_path("tesseract"):
        return ""
    suffix = ext if ext.startswith(".") else f".{ext or 'png'}"
    if suffix not in _IMAGE_EXT:
        suffix = ".png"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"page{suffix}"
            out_base = Path(tmp) / "out"
            src.write_bytes(data)
            proc = _run_cli(["tesseract", str(src), str(out_base), "-l", "eng"], timeout=45)
            if proc is None:
                return ""
            dest = Path(str(out_base) + ".txt")
            if dest.is_file():
                return dest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return ""


@dataclass(frozen=True)
class TextExtract:
    text: str = ""
    extractor: str = "none"
    tools_missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tools_missing"] = list(self.tools_missing)
        return data


def extract_text(data: bytes, filename: str = "") -> TextExtract:
    """Pull text locally. Missing CLI tools degrade to empty text, never raise."""
    payload = data or b""
    name = Path(filename or "document").name
    ext = Path(name).suffix.lower()
    missing: list[str] = []

    if ext in _TEXT_EXT or (ext not in _IMAGE_EXT and ext != ".pdf" and _looks_like_text(payload)):
        text = _decode_text(payload)
        if text.strip():
            return TextExtract(text=text, extractor="text")

    if ext == ".pdf" or payload[:5] == b"%PDF-":
        text = _pdf_parentheticals(payload)
        if text.strip():
            return TextExtract(text=text, extractor="pdf-text")
        if _on_path("pdftotext"):
            cli_text = _run_pdftotext(payload)
            if (cli_text or "").strip():
                return TextExtract(text=cli_text, extractor="pdftotext")
        else:
            missing.append("pdftotext")
        if not _on_path("tesseract"):
            missing.append("tesseract")
        return TextExtract(text="", extractor="none", tools_missing=tuple(missing))

    if ext in _IMAGE_EXT:
        if _on_path("tesseract"):
            ocr = _run_tesseract(payload, ext)
            if (ocr or "").strip():
                return TextExtract(text=ocr, extractor="tesseract")
            return TextExtract(text="", extractor="none")
        return TextExtract(text="", extractor="none", tools_missing=("tesseract",))

    if _looks_like_text(payload):
        return TextExtract(text=_decode_text(payload), extractor="text")
    return TextExtract(text="", extractor="none", tools_missing=tuple(missing))


def _sentences(text: str) -> list[str]:
    found: list[str] = []
    for para in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        compact = " ".join(para.split()).strip()
        if not compact:
            continue
        parts = _SENTENCE_SPLIT.split(compact) if re.search(r"[.!?]", compact) else [compact]
        for part in parts:
            sentence = " ".join(part.split()).strip()
            if sentence:
                found.append(sentence)
    return found


def extract_quorum_sentences(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sentence in _sentences(text):
        folded = sentence.casefold()
        if "quorum" not in folded and "shall consist of" not in folded:
            continue
        if "quorum" in folded and "shall" not in folded and "consist" not in folded and len(folded) < 24:
            continue
        key = folded
        if key in seen:
            continue
        seen.add(key)
        out.append(sentence)
    return out


def extract_officer_titles(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    body = text or ""
    for match in _TITLE_FIND.finditer(body):
        display = display_title(match.group(1))
        key = normalize_title(display)
        if not key or key in seen or not is_officer_title(display):
            continue
        if key in _WEAK_TITLE_KEYS:
            ctx = body[max(0, match.start() - 24) : match.end() + 24].casefold()
            if "shall" not in ctx and "officer" not in ctx:
                continue
        seen.add(key)
        found.append(display)
    return found


def extract_customs(text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    body = text or ""
    for topic, pattern in _CUSTOM_RULES:
        for match in pattern.finditer(body):
            snippet = " ".join(match.group(0).split()).strip(" .")
            if not snippet:
                continue
            key = f"{topic}:{snippet.casefold()}"
            if key in seen:
                continue
            seen.add(key)
            found.append({"topic": topic, "text": snippet})
    return found


def _parse_count(raw: str) -> int | None:
    folded = (raw or "").strip().casefold()
    if not folded:
        return None
    if folded.isdigit():
        number = int(folded)
        return number if number > 0 else None
    return _NUMBER_WORDS.get(folded)


def suggested_quorum_rule(sentence: str) -> QuorumRule:
    text = " ".join((sentence or "").split()).strip()
    titles = extract_officer_titles(text)
    officers = None
    match = _OTHER_OFFICERS_RE.search(text)
    if match:
        officers = _parse_count(match.group(1))
    members = None
    if "member" in text.casefold():
        mem = _MEMBERS_RE.search(text)
        if mem:
            members = _parse_count(mem.group(1))
    if titles or officers or members:
        return QuorumRule(
            mode="structured",
            presiding_any_of=tuple(titles),
            min_other_officers=officers,
            min_members_total=members,
            notes=text,
        )
    return QuorumRule(mode="text", notes=text)


def _role_key(role: str) -> str:
    return normalize_title(role) or role.casefold()


def _existing_officer(settings: dict[str, Any] | None, title: str) -> Officer | None:
    wanted = _role_key(title)
    if not wanted:
        return None
    for officer in resolve_officers(settings):
        if _role_key(officer.role) == wanted:
            return officer
    return None


def _quorum_item(index: int, sentence: str, settings: dict[str, Any] | None) -> dict[str, Any]:
    current = normalize_quorum_rule((settings or {}).get("quorum_rule"))
    rule = suggested_quorum_rule(sentence)
    overwrite = current.mode != "none"
    return {
        "id": f"quorum-{index}",
        "kind": "quorum",
        "text": sentence,
        "rule": rule.to_dict(),
        "readonly": False,
        "would_overwrite": overwrite,
        "current": preview_rule(current) if overwrite else "",
        "proposed": preview_rule(rule),
        "change": (
            f"Would replace current quorum rule ({preview_rule(current)}) with: {preview_rule(rule)}"
            if overwrite
            else f"Would set quorum rule: {preview_rule(rule)}"
        ),
    }


def _officer_item(index: int, title: str, settings: dict[str, Any] | None) -> dict[str, Any]:
    existing = _existing_officer(settings, title)
    display = display_title(title) or title
    if existing:
        who = existing.name or "(no name)"
        return {
            "id": f"officer-{index}",
            "kind": "officer",
            "text": display,
            "title": display,
            "readonly": False,
            "would_overwrite": True,
            "current": f"{existing.role} — {who}",
            "proposed": f"{display} (name left blank)",
            "change": f"Already stored: {existing.role} — {who}. Confirm replace to change this role.",
        }
    return {
        "id": f"officer-{index}",
        "kind": "officer",
        "text": display,
        "title": display,
        "readonly": False,
        "would_overwrite": False,
        "current": "",
        "proposed": f"{display} (name left blank)",
        "change": f"Would add officer role {display} with the name left blank.",
    }


def _custom_item(index: int, row: dict[str, str]) -> dict[str, Any]:
    return {
        "id": f"custom-{index}",
        "kind": "custom",
        "text": row["text"],
        "topic": row["topic"],
        "title": "",
        "readonly": True,
        "would_overwrite": False,
        "current": "",
        "proposed": "",
        "change": "Reminder only. Not applied to the quorum rule or officers.",
    }


@dataclass
class BylawsScan:
    filename: str = ""
    label: str = ""
    text: str = ""
    extractor: str = "none"
    tools_missing: tuple[str, ...] = ()
    found: bool = False
    message: str = NO_TEXT_MESSAGE
    quorum: list[dict[str, Any]] = field(default_factory=list)
    officers: list[dict[str, Any]] = field(default_factory=list)
    customs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "label": self.label,
            "text": self.text,
            "extractor": self.extractor,
            "tools_missing": list(self.tools_missing),
            "found": self.found,
            "message": self.message,
            "quorum": list(self.quorum),
            "officers": list(self.officers),
            "customs": list(self.customs),
        }


def _failure_message(extracted: TextExtract) -> str:
    if extracted.text.strip():
        return NO_MATCH_MESSAGE
    if extracted.tools_missing == ("tesseract",):
        return OCR_ABSENT_MESSAGE
    if extracted.tools_missing:
        missing = ", ".join(extracted.tools_missing)
        return f"No readable text in this file (missing local tools: {missing}). {KEEP_FILE_FALLBACK}"
    return NO_TEXT_MESSAGE


def scan_text(
    text: str,
    filename: str = "",
    label: str = "bylaws",
    settings: dict[str, Any] | None = None,
    extractor: str = "text",
    tools_missing: tuple[str, ...] = (),
) -> BylawsScan:
    """Pure pattern match. Does not write settings or the vault."""
    body = text or ""
    quorum = [_quorum_item(i, sentence, settings) for i, sentence in enumerate(extract_quorum_sentences(body))]
    officers = [_officer_item(i, title, settings) for i, title in enumerate(extract_officer_titles(body))]
    customs = [_custom_item(i, row) for i, row in enumerate(extract_customs(body))]
    found = bool(quorum or officers or customs)
    extracted = TextExtract(text=body, extractor=extractor, tools_missing=tools_missing)
    return BylawsScan(
        filename=filename,
        label=normalize_doc_label(label) if label else "",
        text=body,
        extractor=extractor,
        tools_missing=tools_missing,
        found=found,
        message=SUGGEST_MESSAGE if found else _failure_message(extracted),
        quorum=quorum,
        officers=officers,
        customs=customs,
    )


def scan_bytes(
    data: bytes,
    filename: str = "",
    label: str = "bylaws",
    settings: dict[str, Any] | None = None,
) -> BylawsScan:
    extracted = extract_text(data, filename=filename)
    return scan_text(
        extracted.text,
        filename=filename,
        label=label,
        settings=settings,
        extractor=extracted.extractor,
        tools_missing=extracted.tools_missing,
    )


@dataclass
class ApplyPlan:
    update: dict[str, Any] = field(default_factory=dict)
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "update": dict(self.update),
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "settings": dict(self.settings),
        }


def _rule_from_payload(item: dict[str, Any]) -> QuorumRule:
    if isinstance(item.get("rule"), dict):
        rule = normalize_quorum_rule(item.get("rule"))
        if rule.mode != "none":
            notes = " ".join(str(item.get("text") or rule.notes or "").split()).strip()
            return QuorumRule(
                mode=rule.mode,
                presiding_any_of=rule.presiding_any_of,
                min_other_officers=rule.min_other_officers,
                min_members_total=rule.min_members_total,
                notes=notes or rule.notes,
            )
    text = " ".join(str(item.get("text") or "").split()).strip()
    if not text:
        return QuorumRule()
    return suggested_quorum_rule(text)


def plan_apply(settings: dict[str, Any] | None, payload: dict[str, Any] | None) -> ApplyPlan:
    """Decide what confirm would write. Never writes. Customs are ignored."""
    prefs = dict(settings or {})
    body = dict(payload or {})
    plan = ApplyPlan()

    quorum_item = body.get("quorum")
    if isinstance(quorum_item, dict) and quorum_item.get("confirm"):
        new_rule = _rule_from_payload(quorum_item)
        current = normalize_quorum_rule(prefs.get("quorum_rule"))
        if new_rule.mode == "none" or not (new_rule.notes or new_rule.presiding_any_of or new_rule.min_other_officers or new_rule.min_members_total):
            plan.skipped.append({"kind": "quorum", "reason": "empty"})
        elif current.mode != "none" and not quorum_item.get("overwrite"):
            plan.skipped.append(
                {
                    "kind": "quorum",
                    "reason": "exists",
                    "current": preview_rule(current),
                    "proposed": preview_rule(new_rule),
                    "change": (
                        f"Would replace current quorum rule ({preview_rule(current)}) "
                        f"with: {preview_rule(new_rule)}"
                    ),
                }
            )
        else:
            plan.update["quorum_rule"] = new_rule.to_dict()
            plan.applied.append(
                {
                    "kind": "quorum",
                    "rule": new_rule.to_dict(),
                    "text": new_rule.notes,
                    "overwrote": current.mode != "none",
                }
            )

    current_officers = list(resolve_officers(prefs))
    by_role = {_role_key(officer.role): officer for officer in current_officers}
    officer_changed = False
    for raw in body.get("officers") or []:
        if not isinstance(raw, dict) or not raw.get("confirm"):
            continue
        title = display_title(str(raw.get("title") or raw.get("text") or "").strip())
        if not title or not is_officer_title(title):
            plan.skipped.append({"kind": "officer", "reason": "empty"})
            continue
        existing = by_role.get(_role_key(title))
        if existing and not raw.get("overwrite"):
            plan.skipped.append(
                {
                    "kind": "officer",
                    "title": existing.role,
                    "reason": "exists",
                    "current": f"{existing.role} — {existing.name or '(no name)'}",
                    "proposed": f"{title} (name left blank)",
                    "change": (
                        f"Already stored: {existing.role} — {existing.name or '(no name)'}. "
                        "Not changed."
                    ),
                }
            )
            continue
        if existing and raw.get("overwrite"):
            plan.skipped.append(
                {
                    "kind": "officer",
                    "title": existing.role,
                    "reason": "kept",
                    "current": f"{existing.role} — {existing.name or '(no name)'}",
                    "change": f"Kept existing {existing.role} — {existing.name or '(no name)'}.",
                }
            )
            continue
        current_officers = add_officer_role(current_officers, title, "")
        added = next(
            (officer for officer in current_officers if _role_key(officer.role) == _role_key(title)),
            Officer(role=title, name=""),
        )
        by_role[_role_key(title)] = added
        officer_changed = True
        plan.applied.append({"kind": "officer", "title": title, "name": ""})

    if officer_changed:
        plan.update["officers"] = officers_to_dicts(current_officers)
    return plan


def apply_confirmed(settings: dict[str, Any] | None, payload: dict[str, Any] | None) -> ApplyPlan:
    """Write confirmed quorum / officer suggestions. Customs are never stored as features."""
    plan = plan_apply(settings if settings is not None else app_settings.load_settings(), payload)
    if plan.update:
        plan.settings = app_settings.save_settings(plan.update)
    else:
        plan.settings = dict(settings if settings is not None else app_settings.load_settings())
    return plan
