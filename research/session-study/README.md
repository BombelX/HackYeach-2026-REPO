> This is the original research snapshot. Use [the current collector](../../README.md#session-collector--separate-application) for the maintained collection app. See [research layout](../README.md) for dependencies and consolidation limits.

# Bank24 — research data collection platform (HackYeah 2026)

A simulated banking site using two-step sign-in and its own **Bank24** branding.
Participants complete calm sign-ins, dictated transfer details, pressure from a
simulated bank employee and an intruder scenario. A shared clock records:

- Optional camera video and face/pose/skin-RGB measurements.
- Timestamped keyboard and mouse events.
- Browser environment, Resource Timing, ping RTT and IP/ASN.

This is **not a real bank**. Repeated banners/footer identify the research site.
It does not copy Pekao's name or logo or request real bank credentials.

## Quick start — Windows

Run inside `research/session-study/`:

```powershell
cd web
npm install
cd ../server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start two terminals:

```powershell
# API
cd server
.\.venv\Scripts\Activate.ps1
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# UI
cd web
npm run dev
```

Or use `./scripts/start.ps1`. Open http://localhost:5173 for the study and
http://localhost:5173/admin for the facilitator panel. Historical default panel
password: `hackyeah`; configure `ADMIN_PASSWORD` for your environment.
The standalone collector is maintained separately in `data-collector/`.

## HTTPS / camera tunnel

Browser camera access requires HTTPS outside localhost. For example:

```powershell
cloudflared tunnel --url http://127.0.0.1:5173
```

For event hosting, build with `npm run build` inside `web/`, let uvicorn serve
`web/dist` on 8000, and tunnel that port.

## Study flow, approximately 12 minutes

1. Enter an issued participant code (`P-…`) or start a new study.
2. Choose consent, with video consent separate.
3. Camera calibration (the original protocol specified 60 seconds; current UI uses 20).
4. Memorize fictional personal credentials.
5. Two calm sessions, randomized dictation/scam/intruder sessions, then a final calm session.
6. Rate stress and hurry from 1 to 7 after each session.

Intruder: show leaked credentials for 20 seconds, allow 90 seconds to transfer from
another account, and present a random new-device alert. Scam: a simulated support
contact dictates a technical account with a two-minute countdown.

## Data

```text
data/participants.sqlite
data/sessions/<id>/meta.json
data/sessions/<id>/events.jsonl
data/sessions/<id>/face.jsonl
data/sessions/<id>/net.jsonl
data/sessions/<id>/video/*.webm
data/sessions/<id>/survey.json
```

Export stage-level features and signal masks to Parquet:

```powershell
cd server
.\.venv\Scripts\python.exe export.py --out ../data/export
```

## Training infrastructure

Training is separate from this application. Collect on a laptop with a tunnel.
The historical Vast.ai setup reserved 400–500 GB initially because that instance's
disk could not later be enlarged; check your provider's current options before use.
