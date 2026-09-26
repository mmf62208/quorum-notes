# FORGE STATUS — GO C1 minutes house style

Draft / HOLD. Do not merge.

- **PR:** https://github.com/mmf62208/quorum-notes/pull/7
- **Branch:** `cursor/minutes-house-style-6d76`
- **Base:** `main` (`12e0c11`)
- **Head:** `57b153b203cb41ee4571cbb765f7b436200d8b46` (plus this status SHA fix on the same branch)
- **Tests:** `python3 -m unittest discover -s tests -v` — **125 passed** (108 existing + 17 new). 0 failed.
- **Browser:** Setup closing-line field + a full Sep-22-shaped draft were clicked through. Record stayed available.
- **Screenshots (not committed):**
  - `/opt/cursor/artifacts/screenshots/c1-minutes-draft.png`
  - `/opt/cursor/artifacts/screenshots/c1-closing-line-setting.png`
  - `/opt/cursor/artifacts/screenshots/c1-minutes-no-closing.png`
  - `/opt/cursor/artifacts/screenshots/c1-minutes-closing-restored.png`
- **Samples (not committed):**
  - `/opt/cursor/artifacts/minutes-before.md` (renderer at `12e0c11`)
  - `/opt/cursor/artifacts/minutes-after.md` (this change)

Synthetic fixture only. No Sep 22 gold minutes and no real member names were committed.

## What landed

- Run-in bold headers for single-block sections; list sections keep header + bullets.
- Full names on the officer roll; body/motions use first name, `Mike F.` / `Mike G.` when first names collide, first + last name when initials also collide. Name source is B3 officer memory plus the meeting roster.
- Motions: `Herm moved to …; Randy seconded. Motion carried.`
- B2 single quorum line unchanged; `org_quorum_line_edited` still protects hand edits.
- Signature: `Respectfully submitted,` / adjutant full name / `Adjutant, <org>` / optional per-org closing line.
- `minutes_closing` in the local vault settings. Blank or missing = no line. SAL 484 prefill (`For God and Country`) is a Setup button, never auto-applied.
- No em dashes in generated text.

## Before / after (same synthetic Sep-22-shaped meeting)

### Before (`12e0c11`)

```
**Roll Call / Quorum:**
Members present included:

Pat Hale, Sam Ortiz, Ted Brooks, Mike Foster, Randy Cole, Herm Walsh, Mike Grant.

Guests: Alex Reed.

Quorum: Met (Commander presiding; 6 other officers present).

**Finance Officer** (Ted Brooks)
Presented the printed financial report for June-August activity.

1. Herm Walsh moved that accept the financial report as presented; Randy Cole seconded. The motion carried. (Yea 7, Nay 0, Abstain 0)

For God and Country

**Takeaways / assignments:**

* Replenish the cash box before breakfast — Ted Brooks

**Respectfully submitted,**

**Mike Foster**
**Adjutant**
```

### After (C1)

```
**Roll Call / Quorum:** Commander Pat Hale conducted roll call.

**Officers:**
* Commander Pat Hale, present
* 1st Vice Commander Chris Lang, absent
* Adjutant Mike Foster (Mike F.), present
* Historian Mike Grant (Mike G.), present

**Members / guests also present:** Alex Reed.

Quorum: Met (Commander presiding; 6 other officers present).

**Finance Officer (Ted):** Presented the printed financial report for June-August activity.

1. Herm moved to accept the financial report as presented; Randy seconded. Motion carried. (Yea 7, Nay 0, Abstain 0)

**Takeaways / assignments:**
* Replenish the cash box before breakfast (Ted Brooks)

**Respectfully submitted,**

**Mike Foster**

**Adjutant, Example Squadron 12**

**For God and Country**
```
