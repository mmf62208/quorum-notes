"""Turn a sign-in sheet review into a present list. No invented names."""

from __future__ import annotations


def normalize_name(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def merge_present(
    roster: list[str],
    present: list[str],
    sheet_names: list[str],
) -> dict[str, list[str]]:
    """Match sheet names onto the roster. Unmatched names are returned, not auto-added as members."""
    roster_map = {normalize_name(n): n for n in roster if n}
    already = [n for n in present if n]
    already_keys = {normalize_name(n) for n in already}
    matched: list[str] = []
    unmatched: list[str] = []
    for raw in sheet_names:
        name = " ".join((raw or "").split())
        if not name:
            continue
        key = normalize_name(name)
        if key in roster_map:
            official = roster_map[key]
            if normalize_name(official) not in already_keys:
                already.append(official)
                already_keys.add(normalize_name(official))
                matched.append(official)
        else:
            unmatched.append(name)
    return {"present": already, "matched": matched, "unmatched": unmatched}
