# Quorum

Privacy-first meeting assistant for civic officers: record the room, mark who is present and who spoke, track 1st / 2nd / vote, email the minutes. Advanced AI is **opt-in only** (SpaceXAI). MIT.

Built for in-person lodge/post meetings first (phone in your hand), with desktop and Zoom still supported.

## Run on this computer

```bash
cd ~/Projects/quorum-notes
python3 -m quorum
```

Open [http://127.0.0.1:4840](http://127.0.0.1:4840). First launch asks org, retention, and roster.

### Give it to another desktop tester

```bash
tools/pack_tester.sh
```

Send `dist/quorum-tester.zip`. They need Python 3.11+:

```bash
unzip quorum-tester.zip
cd quorum-notes   # or whatever folder unzip created
python3 -m quorum
```

### Phones at the hall (same Wi‑Fi)

On the laptop that is recording the official vault:

```bash
QUORUM_HOST=0.0.0.0 python3 -m quorum
```

Phones on that network open `http://<laptop-lan-ip>:4840`. Data stays on the laptop. Do not expose that port to the public internet.

Add to Home Screen from the phone browser for a full-screen tester app.

## In a meeting

1. **Start meeting** — auto-named file; SAL opening ceremonies are filled in.
2. **Hear the room** — pick the mic (headset / speakerphone / Bluetooth). The meter must move before Record.
3. Tap names for **present**. **Mark late** then tap. While recording, tap a name to mark **who is talking**.
4. Type a motion → **1st** → tap → **2nd** → tap → **Carried** / **Failed**. No second, no carry when Robert’s Rules is on.
5. Take a **sign-in** or document photo.
6. **Stop** → listen back (−15 / +15 / speed, or tap a speaker mark) → **Email**, **Download**, or **Print / PDF**.
7. **Mark minutes approved** — if retention is “until approved,” the WAV is deleted; the minutes stay.

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
