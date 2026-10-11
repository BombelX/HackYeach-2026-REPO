# Live camera analysis

## Bank24 React application

The integrated Bank24 application is in [frontend/](frontend/README.md), with
an SQLite API in [bank24_server.py](bank24_server.py). Run
`./.venv-bank/Scripts/python.exe bank24_server.py --demo` and `npm run dev`
from `frontend/`, then open http://localhost:5173/. The landing page leads to
login (`anna.demo` / `bank24`) and the demo OTP `1234`; there is no participant
code step and SMS is not sent. Installation, camera permissions and tests are
in the frontend README; the implemented contract is in [BANK24_API.md](BANK24_API.md).
Bank and study data persist on the server. Camera inference and risk results
are never silently replaced with illustrative values. PhysNet assets are absent in this checkout: use the worker's `--preview-only`
mode or pass `--toolbox /path/to/rPPG-Toolbox` to point at an external source
tree with its checkpoint. The Bank24 frontend sends JPEG frames through its
authenticated HTTPS gateway and renders the server's annotated image and
landmark data; the standalone WebRTC demo below remains available separately.

### Camera-based transfer risk

When the signed-in session has an active camera, `POST /api/bank/transfers` scores the transfer with the
fusion model from `training/inference_xgb_suspicious.py` of the hackaton repo (`--fusion-repo`, default
`/workspace/hackaton/HackYeach-2026-REPO`; env `BANK24_FUSION_REPO`). Bank24 fetches the worker's
`/trace`, writes it as `pulse/timeline/frames.parquet` ([bank24_camera_risk.py](bank24_camera_risk.py)) and calls
`predict_suspicious`. Camera enrolment is explicit in the signed-in Bank24 app. The owner confirms
each calm recording after an explicit start and at least 40 s of recording, with the face visible in
most analysis windows. Three approved samples
from separately verified logins create profile version 1. In demo mode the first three samples are
approved automatically for calibration; outside demo mode they require operator approval. After a
profile exists, each new sample remains pending until the operator independently verifies the owner.
Approval creates a new version using the latest five approved samples. Configure `BANK24_ADMIN_TOKEN`
to enable operator approval; without it, further enrolment is disabled once the demo profile is ready.
Profiles and sample history are
stored per account in `data/bank24.sqlite`.
Risk checks never create or update a profile. Newly created profile versions take effect at the next
login; the current recording is not scored against a version that contains that recording. The model's
own score cannot authorize an update; the demo alarm session is excluded. The user can delete all
camera samples and versions from the profile panel. Existing legacy `data/camera_profiles/*.pkl` files
are not imported because their enrolment was automatic and unverified. Older SQLite profile rows are
retained but marked untrusted during migration, so they are not used for risk decisions until approved
samples create a new version. Later transfers score the last
120 s against the latest saved version. `p_not_owner`/`p_pressure` are shown as 0–100,
and `review_required` requests additional verification. Keyboard, mouse and device inputs are masked, so the
result is an unvalidated demo signal. Without a camera or enough data the previous `insufficient_data`
assessment is returned with the reason.

The SQLite database survives process restarts. On a Vast instance it survives recycle/destroy only
when the database directory is backed by a persistent volume or synchronized externally.
The demo code `1234` and a low camera mismatch score do not independently prove account ownership;
this enrolment is a per-account calibration flow, not a production identity verification process.

The camera starts automatically after login (consent is granted at sign-in for non-study sessions) and the
frontend calls `POST /api/bank/risk-check` every 8 s. Camera-only scores are unvalidated and can request
additional review, but they do not automatically log out the user. The model documentation specifies review,
not blocking; the reported cross-validation did not evaluate this camera-only deployment path.
Demo mode only: the SMS code `4321` (`--alarm-code`) forces a synthetic mismatch to 93–99/100 after
`alarm_delay` and can trigger the `--risk-logout` threshold (default 70). The server then ends the session,
cancels unconfirmed transfers and returns `403 anomaly_detected`; the frontend shows the warning and
redirects to login. A transfer confirmed with the alarm code is held (`409 transfer_held`).

## Bank24 application plan and mockups

The development plan based on branch `backend` is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). The interactive Bank24 prototype is in [mockups/](mockups/README.md), covering login, SMS, dashboard, transfer and a safety warning. Run it separately with `python -m http.server 5174 --bind 127.0.0.1 --directory mockups` and open http://localhost:5174. Its banking data, camera metrics and risk explanations are illustrative; the optional camera view stays local. Demo credentials: `anna.demo` / `bank24`, SMS code `1234`.

The completed frontend reimplementation and acceptance record are in [FRONTEND_REIMPLEMENTATION_PLAN.md](FRONTEND_REIMPLEMENTATION_PLAN.md). The prototype includes functional demo history and help, standard and intervention transfer scenarios, and a vector [Bank24 identity board](mockups/brand.html).

The server processes browser camera frames through the authenticated Bank24 HTTPS gateway or the standalone WebRTC demo, runs PhysNet pulse and MediaPipe landmark detection, and returns annotated frames and measurements. Each session has separate models and history. WebRTC media queues keep only the newest frame so slow inference does not build a backlog. No local server camera or GUI is required.

## Run

```bash
venv/bin/python -m pip install -r requirements-server.txt
venv/bin/python webrtc_server.py --device cpu
```

Open http://localhost:8080 and select **Start camera**. To test transport without loading analysis models:

```bash
venv/bin/python webrtc_server.py --preview-only --no-analysis
```

If no camera prompt appears, check the page's status message. On the server computer, use `http://localhost:8080` instead of an HTTP LAN IP address. From another computer or phone, use HTTPS with a certificate trusted by that device:

```bash
venv/bin/python webrtc_server.py --ssl-cert /path/to/cert.pem --ssl-key /path/to/key.pem
```

Open `https://your-server-hostname:8080` with the hostname covered by that certificate. An HTTPS reverse proxy also works. If camera permission was previously denied, allow it in the browser's site settings and click **Start camera** again. An embedded page also needs camera permission from its containing page.

Default assets are in `models/` and `rPPG-Toolbox/final_model_release/`. Override with `--weights`, `--pose-model`, or `--face-model`. `--no-analysis` disables MediaPipe landmark detection; `--preview-only` disables pulse estimation. Results use `null` until an actual heart-rate estimate is available; there are no placeholder BPM values. Estimates are experimental, not medical measurements.

## Input and output endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/webrtc/offer` | Input signaling: JSON `{ "sdp": "...", "type": "offer" }`; returns SDP answer, `session_id`, `output_url`, `events_url` |
| GET | `/api/sessions/{session_id}/output` | Output: most recent JSON analysis |
| WebSocket | `/api/sessions/{session_id}/events` | Output: live JSON analysis, initial snapshot then updates |
| DELETE | `/api/sessions/{session_id}` | Close peer connection and release session resources |
| GET | `/health` | Server status and active session count |
| POST | `/api/frames/sessions` | Start a JPEG-frame analysis session; returns `session_id` |
| POST | `/api/frames/sessions/{session_id}/frame` | Send `image/jpeg` (at most 256 KiB, at most 960 px per side); returns `{measurement, image}` with a base64 JPEG of the annotated frame |
| DELETE | `/api/frames/sessions/{session_id}` | Release analysis resources |
| GET | `/api/sessions/{session_id}/trace` | Recorded per-frame features (pulse, spectral concentration, 20 face blendshapes, posture, face box; last 10 min) for either session type; used by Bank24 risk scoring |

In the standalone WebRTC demo, frames travel as RTP media rather than HTTP uploads. The offer must include one outgoing video track. Use `sendrecv` (the default for browser `addTrack`) to also receive annotated video. A `sendonly` offer still feeds the analyzer and exposes JSON output. Audio is not processed. Wait for client ICE gathering to complete **before** POSTing the offer; this implementation uses complete SDP exchange, without a separate trickle-ICE endpoint. See `static/webrtc.html` for a complete client. Bank24 instead sends bounded JPEG frames through its same-origin HTTPS API; it does not require TURN.

Example output:

```json
{
  "session_id": "...",
  "timestamp": 1791036000.0,
  "status": "measuring",
  "face_detected": true,
  "heart_rate_bpm": 72.3,
  "heart_rate_stale": false,
  "heart_rate_updated_at": 1791036000.0,
  "sampling_fps": 29.8,
  "window_seconds": 8.5,
  "landmarks": {
    "pose": [{"index": 0, "x": 0.51, "y": 0.08, "z": -0.24}],
    "face": [{"index": 0, "x": 0.52, "y": 0.34, "z": -0.04}]
  },
  "landmarks_timestamp_ms": 153426,
  "frame_width": 640,
  "frame_height": 480
}
```

Status values include `waiting`, `warming_up`, `measuring`, `stale`, `preview`, `ended`, `error`, and `closed`. `heart_rate_stale` identifies an older pulse reading left visible while fresh samples are collected; `heart_rate_updated_at` records the last successful pulse inference. `landmarks` holds the normalized raw pose and face coordinates, and the returned video draws all of them in cyan. Losing the face or a sampling gap clears the sampling window and marks a prior pulse as stale. Polling an unknown/deleted/expired session returns 404. Active sessions are limited by `--max-sessions` (default 4), and their lifetime by `--session-timeout` (default 3600 seconds).

Remote browser camera access requires HTTPS (localhost works with HTTP). For the standalone WebRTC demo across networks, configure reachable STUN/TURN servers on both the browser and server, e.g. `--ice-servers '[{"urls":"stun:stun.example.com:3478"}]'`, and allow WebRTC UDP traffic or use TURN. The included demo defaults to host candidates only. The worker API has no authentication; bind `--host 127.0.0.1` for local use or put it behind Bank24's authenticated gateway before exposing it publicly. Session IDs grant access to worker output if the worker is exposed directly.

## Verification

```bash
venv/bin/python -m unittest discover -s tests -v
```
