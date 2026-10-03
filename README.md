# Live WebRTC camera analysis

The server receives a browser camera feed over WebRTC, runs the existing PhysNet pulse and MediaPipe posture/expression analysis, and returns annotated video over the same peer connection. Each session has separate models and history. Media queues keep only the newest frame so slow inference does not build a backlog. No local server camera or GUI is required.

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

Default assets are in `models/` and `rPPG-Toolbox/final_model_release/`. Override with `--weights`, `--pose-model`, or `--face-model`. `--no-analysis` disables MediaPipe; `--preview-only` disables pulse estimation. Results use `null` until an actual heart-rate estimate is available; there are no placeholder BPM values. Estimates are experimental, not medical measurements.

## Input and output endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/webrtc/offer` | Input signaling: JSON `{ "sdp": "...", "type": "offer" }`; returns SDP answer, `session_id`, `output_url`, `events_url` |
| GET | `/api/sessions/{session_id}/output` | Output: most recent JSON analysis |
| WebSocket | `/api/sessions/{session_id}/events` | Output: live JSON analysis, initial snapshot then updates |
| DELETE | `/api/sessions/{session_id}` | Close peer connection and release session resources |
| GET | `/health` | Server status and active session count |

The camera frames themselves travel as WebRTC RTP media, rather than HTTP uploads. The offer must include one outgoing video track. Use `sendrecv` (the default for browser `addTrack`) to also receive annotated video. A `sendonly` offer still feeds the analyzer and exposes JSON output. Audio is not processed. Wait for client ICE gathering to complete **before** POSTing the offer; this implementation uses complete SDP exchange, without a separate trickle-ICE endpoint. See `static/webrtc.html` for a complete client.

Example output:

```json
{
  "session_id": "...",
  "timestamp": 1791036000.0,
  "status": "measuring",
  "face_detected": true,
  "heart_rate_bpm": 72.3,
  "sampling_fps": 29.8,
  "window_seconds": 8.5,
  "posture": "upright",
  "expression": "neutral"
}
```

Status values include `waiting`, `warming_up`, `measuring`, `preview`, `ended`, `error`, and `closed`. Disabled posture/expression fields are `null`. Losing the face or a sampling gap clears pulse history and the current estimate. Polling an unknown/deleted/expired session returns 404. Active sessions are limited by `--max-sessions` (default 4), and their lifetime by `--session-timeout` (default 3600 seconds).

Remote browser camera access requires HTTPS (localhost works with HTTP). Across networks, configure reachable STUN/TURN servers on both the browser and server, e.g. `--ice-servers '[{"urls":"stun:stun.example.com:3478"}]'`, and allow WebRTC UDP traffic or use TURN. The included demo defaults to host candidates only. The API has no authentication; bind `--host 127.0.0.1` for local use or put it behind your application's authenticated HTTPS proxy before exposing it publicly. Session IDs grant access to session output.

## Verification

```bash
venv/bin/python -m unittest discover -s tests -v
```
