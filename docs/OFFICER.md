# Quorum — officer one-pager

For the adjutant or secretary running a meeting on a laptop or phone.

## Before the meeting

1. Unzip, double-click **Start Quorum**. The console opens at http://127.0.0.1:4840. Fallback: `python3 -m quorum`.
2. Complete **Setup** once: organization, your name, roster, how long to keep recordings.
3. For phones in the hall: `QUORUM_HOST=0.0.0.0 python3 -m quorum` and open the **phones:** URL on the same Wi‑Fi.
4. Tap **Hear the room**. The meter must move before you trust Record.

## During

1. **Start meeting** or **Dry-run** (practice).
2. Follow **Next**: Opening → Roll call → Previous minutes → Reports → Old / New business → Good of the order → Adjourn.
3. Tap names present. **Mark late** then tap. While recording, tap a name to mark who is talking.
4. Motions: type the motion → **1st** → tap → **2nd** → tap → **Carried** / **Failed**. No second, no carry.
5. Keys: `1` first, `2` second, `V` carried, `Ctrl+Z` undo.
6. Sign-in photo → tick names you see → **Apply sign-in**.

## After

1. Stop recording. Listen back (−15 / +15) if needed.
2. **Email minutes**, **Download**, or **Print / PDF**.
3. **Mark minutes approved** if you chose “until approved” — that deletes the tape, not the minutes.
4. **Backup** before you close the laptop.

Nothing leaves this device unless you tap **Polish with SpaceXAI** and have set `XAI_API_KEY`.
