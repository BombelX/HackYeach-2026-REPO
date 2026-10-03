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

Status values include `waiting`, `warming_up`, `measuring`, `stale`, `preview`, `ended`, `error`, and `closed`. Disabled posture/expression fields are `null`. Losing the face clears pulse history but retains the last measured heart rate. Dropped frames and sampling gaps preserve the rolling queue; timestamps are used to interpolate missing samples. Output marks it with `heart_rate_stale: true`, status `stale`, and `heart_rate_updated_at` (Unix seconds of its last update). Each processed frame continues to publish this value until fresh measurements resume. Before the first measurement, BPM remains `null`; ended/closed/error sessions clear it. Polling an unknown/deleted/expired session returns 404. Active sessions are limited by `--max-sessions` (default 4), and their lifetime by `--session-timeout` (default 3600 seconds).

Remote browser camera access requires HTTPS (localhost works with HTTP). Across networks, configure reachable STUN/TURN servers on both the browser and server, e.g. `--ice-servers '[{"urls":"stun:stun.example.com:3478"}]'`, and allow WebRTC UDP traffic or use TURN. The included demo defaults to host candidates only. The API has no authentication; bind `--host 127.0.0.1` for local use or put it behind your application's authenticated HTTPS proxy before exposing it publicly. Session IDs grant access to session output.

## Verification

```bash
venv/bin/python -m unittest discover -s tests -v
```

## Heart rate pipeline and improvements

The shared pulse estimator lives in `camera_estimator.py`; `webrtc_server.py`
maintains separate capture and inference history for each session.

1. **Capture:** browser video arrives through WebRTC. A one-frame queue drops old
   frames when processing falls behind. Currently timestamps record server arrival
   time, not camera exposure time.
2. **Find and crop a face:** a Haar detector runs every 15 processed frames, selects
   the largest face, and smooths its bounding box by 20% per frame. The box is
   enlarged by 1.5, clipped, resized to 72 × 72, and converted from BGR to RGB.
3. **Sample and normalize:** keep up to 128 crops with timestamps, capped near
   `--fps`. Interpolate each inference window onto uniform timestamps; compute
   adjacent-frame differences divided by adjacent-frame sums, scale by their
   standard deviation, and append a zero frame to match checkpoint preprocessing.
4. **Infer the pulse:** the UBFC-rPPG DiffNormalized PhysNet checkpoint produces
   one difference-label prediction per frame. Inference starts at `--min-frames`
   and repeats every 0.5 seconds when a new sample is available. Each update uses
   the newest frame together with queued previous crops, up to 128 frames; old
   crops roll out automatically. `--stride` is retained as a legacy argument and
   no longer controls cadence. Window lengths are multiples of four.
   PhysNet learns spatial and temporal features from facial video; see the
   [original paper](https://arxiv.org/abs/1905.02419).
5. **Build history:** new overlapping predictions replace older predictions for
   the same interval. Keep approximately `--window` seconds (default 10), then
   resample the combined predictions uniformly.
6. **Estimate BPM:** integrate difference predictions, remove a smooth trend,
   apply a zero-phase 0.75–2.5 Hz bandpass, and compute a Hann-window periodogram.
   Select a local spectral peak in 45–150 BPM. Prefer a peak within 15 BPM of the
   previous estimate only if its power is at least one third of the strongest peak.
7. **Publish:** the server smooths accepted BPM values with a 0.3 update weight and
   returns JSON via polling/WebSocket. Face loss clears history; missing frames do not restart the queue. Posture and expression run separately; they do not validate BPM.

### Implemented reliability changes

- Require at least five seconds of pulse history before returning BPM. Starting
  neural inference after 32 frames no longer means a valid heart rate is ready.
- Reject short, nonfinite, flat, or invalid-rate inputs before spectral estimation.
- Track actual local spectral peaks: the old prior search could select a bin on
  the slope of a distant peak and return a misleading intermediate BPM.
- Retain the last measured BPM during reacquisition; clear the tracking prior and
  mark server output as stale when estimation fails.
- Disable the local webcam's synthetic 72 BPM placeholder by default.

Five seconds is a minimum observation threshold, not a confidence guarantee.
Zero-padding makes the FFT grid finer but does not improve the underlying
frequency resolution (roughly 60/window-seconds BPM). Periodic motion can still
produce a strong false peak, and the current band excludes rates outside 45–150.

### Next improvements, in priority order

1. **Measure accuracy first:** record videos synchronized with a reference pulse
   sensor. Compare baseline and changed pipelines on held-out people; report MAE,
   RMSE, accepted-reading coverage, first-reading latency, and recovery time after
   motion. Include different lighting, skin tones, cameras, compression, and rates.
   Synthetic tests verify signal processing, not accuracy on faces.
2. **Improve timing:** use monotonic video presentation timestamps (`pts` with
   `time_base`) for pulse sampling, keeping arrival time for transport diagnostics.
   Detect duplicate/backward timestamps and gaps before interpolation. This should
   reduce network-jitter distortion; validate it on recorded streams.
3. **Gate poor recordings:** quantify motion, illumination changes, clipping,
   blur, and spectral concentration; publish quality and rejection reasons.
   Calibrate thresholds against reference data rather than treating any spectral
   maximum as evidence of a pulse. Distinguish warm-up from poor-quality output.
4. **Stabilize face identity and regions:** track one face, reset on identity
   changes, and use landmarks to measure stable cheek/forehead regions. The enlarged
   box currently includes hair/background. Changes to PhysNet crops must be tested
   against its training preprocessing; masking can introduce distribution shift.
5. **Improve inference history:** overlapping model windows can have different
   offsets and amplitudes, creating seams when integrated. Test per-window
   alignment and tapered overlap blending against the current replacement scheme.
6. **Optimize capture throughput:** benchmark actual processed FPS and model time.
   Move expensive inference off capture processing or use a faster validated model
   if processing cannot sustain two updates per second. Longer history trades
   responsiveness for resolution.
7. **Compare methods:** evaluate the toolbox's POS/CHROM baselines and other
   checkpoints on the same recordings. Consider harmonic checks and agreement
   between facial regions. Expand the BPM band only with suitable data and tests;
   neither a new model nor stronger smoothing alone establishes better accuracy.

Heart-rate inference runs at most twice per second using accepted samples (capped
by `--fps`), after initial warm-up. JSON snapshots still publish on each processed
frame, carrying the latest BPM between estimates. If inference or capture is slow,
updates can occur less often. WebRTC may drop incoming frames when processing
cannot keep up; these drops do not clear the rolling pulse queue. Long gaps are
interpolated too, so fresh estimates after a prolonged interruption may be less
reliable even though the queue is retained.
