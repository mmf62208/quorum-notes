# Quorum

Privacy-first meeting assistant for civic officers: record the room, mark who is present and who spoke, track 1st / 2nd / vote, email the minutes. Advanced AI is **opt-in only** (SpaceXAI). MIT.

Built for in-person lodge/post meetings first (phone in your hand), with desktop and Zoom still supported.

## Run on this computer

Unzip, double-click **Start Quorum**. The meeting console opens at [http://127.0.0.1:4840](http://127.0.0.1:4840). First launch asks org, retention, and roster.

Fallback if the launcher does not start:

```bash
cd ~/Projects/quorum-notes
python3 -m quorum
```

### Give it to another desktop tester

```bash
tools/pack_tester.sh
```

Send `dist/quorum-tester.zip`. They need Python 3.11+:

```bash
unzip quorum-tester.zip
```

Open the one `quorum-notes` folder and double-click **Start Quorum**. Fallback: `python3 -m quorum`.

### Phones at the hall (same Wi‑Fi)

On the laptop that is recording the official vault:

```bash
QUORUM_HOST=0.0.0.0 python3 -m quorum
```

Phones on that network open `http://<laptop-lan-ip>:4840`. Data stays on the laptop. Do not expose that port to the public internet.

Add to Home Screen from the phone browser for a full-screen tester app.

## In a meeting

**Dry-run** seeds a practice meeting so you can walk Opening → Roll call → Previous minutes → Reports → Motions → Adjourn → Email.

The sidebar shows phone URLs when the laptop is on Wi‑Fi (use `QUORUM_HOST=0.0.0.0` so those URLs work).

1. **Start meeting** or **Dry-run** — auto-named file; SAL opening ceremonies are filled in. Use **Next** to follow the order of business.
2. **Hear the room** — pick the mic (headset / speakerphone / Bluetooth). The meter must move before Record.
3. Tap names for **present**. **Mark late** then tap. While recording, tap a name to mark **who is talking**.
4. Type a motion → **1st** → tap → **2nd** → tap → **Carried** / **Failed**. No second, no carry when Robert’s Rules is on.
5. Take a **sign-in** or document photo.
6. **Stop** → listen back (−15 / +15 / speed, or tap a speaker mark) → **Email**, **Download**, or **Print / PDF**.
7. After a **sign-in photo**, tick the names you see and **Apply sign-in to present**. Unknown names are not added as members.
8. **Undo** or `Ctrl+Z`. Keys: `1` first, `2` second, `V` carried.
9. **Backup** / **Restore** zip the whole vault. **Mark minutes approved** deletes the WAV if you chose “until approved.”

## What stays on the device

| Path | Contents |
|------|----------|
| `vault/settings.json` | First-run org, roster, retention |
| `vault/meetings/<auto-name>/` | JSON, named WAV, minutes.md, photos in JSON |
| `backups/` | Zip of the vault |

Retention (you pick at setup): until minutes approved · 7 days · 14 days · keep until delete.

Nothing is uploaded unless you tap **Polish with SpaceXAI** and `XAI_API_KEY` is set.

```bash
python3 -m unittest discover -s tests -v
```

That suite includes a **bot** (`tests/test_http_bot.py`) that starts the real server and walks a full meeting: setup, create, reject a carried motion with no second, save a legal motion, sign-in merge, audio, email, download, print, approve (tape gone), dry-run, backup.

Officer one-pager: [`docs/OFFICER.md`](docs/OFFICER.md).
