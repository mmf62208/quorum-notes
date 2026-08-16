# Quorum Notes

Privacy-first meeting capture for civic and lodge work: **WAV recording**, a **local vault**, **zip backups**, and **formal minutes helpers**. Advanced AI is **opt-in only** (SpaceXAI / `XAI_API_KEY`). MIT licensed.

This tree is a **rebuild** on a new CachyOS machine. The GitHub repo `mmf62208/quorum-notes` was created 2026-08-13 with the description above but **no commits**. Prior source and chat transcripts were not on this host, not in Gmail/Drive (except SAL minutes), and not in local Claude/Cursor/Codex sessions. The product spec comes from that GitHub description plus the formal minutes style of [SAL Post 484, 16 June 2026](https://docs.google.com/document/d/1l5QnMjW1LGRNE_-V61uoy1NJAp-xIVNjw5l6PrU-Edo/edit) (adjutant: Mike Featherstone).

## Run

```bash
cd ~/Projects/quorum-notes
python3 -m quorum
```

Then open [http://127.0.0.1:4840](http://127.0.0.1:4840). The server binds **localhost only**.

```bash
python3 -m unittest discover -s tests -v
```

## What it stores

| Path | Contents |
|------|----------|
| `vault/meetings/<id>/meeting.json` | Structured meeting (roll call, motions, reports) |
| `vault/meetings/<id>/audio.wav` | Browser-captured WAV |
| `vault/meetings/<id>/minutes.md` | Formal minutes render |
| `vault/meetings/<id>/transcript.txt` | Only if you opt into SpaceXAI STT |
| `backups/quorum-vault-*.zip` | Local zip of the vault |

Nothing is uploaded unless you click **Opt-in: transcribe** or **Opt-in: draft minutes** and `XAI_API_KEY` is set.

## Formal minutes helpers

- Roll call + **quorum** (majority of roster, or a fixed number)
- Motions: mover, seconder, yeas/nays, carried/failed
- SAL-style Markdown: called to order, opening, quorum, previous minutes, reports, old/new business, adjournment, respectfully submitted
- **Load SAL template** fills Post 484 officer/opening scaffolding

## Optional SpaceXAI

```bash
export XAI_API_KEY=...          # https://console.x.ai
export XAI_MODEL=grok-4.6       # optional
python3 -m quorum
```

- Transcribe uses `POST https://api.x.ai/v1/stt`
- Draft minutes uses `POST https://api.x.ai/v1/responses`
- The API key stays on the server process. The browser never sees it.

## Environment

| Variable | Default |
|----------|---------|
| `QUORUM_HOST` | `127.0.0.1` |
| `QUORUM_PORT` | `4840` |
| `QUORUM_VAULT` | `./vault` |
| `QUORUM_BACKUPS` | `./backups` |
| `XAI_API_KEY` | unset (AI off) |

No third-party Python packages are required for recording, vault, minutes, or backup.
