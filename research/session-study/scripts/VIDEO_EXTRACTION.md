# Recorded Video Extraction

Run from the repository root with the existing analysis environment. First check
which recordings are ready:

```bash
/venv/main/bin/python scripts/extract_video_data.py --inventory-only
```

Run the extractor once to process all scenarios concurrently. It starts one
worker per scenario and pins each worker to its own GPU:

```bash
/venv/main/bin/python scripts/extract_video_data.py --include-incomplete
```

GPU mapping defaults to `calm -> cuda:0`, `dictation -> cuda:1`,
`scam -> cuda:2`, and `intruder -> cuda:3`. Override the mapping with
`--gpu-ids 3 2 1 0`. The automatic mode requires four available CUDA GPUs.
For a single scenario or a smoke test, use `--group` and optionally `--device`.

While processing, each command updates a live progress line with video-time
progress (when duration metadata is available), decoded frame and feature counts,
and processing speed.

The four protocol groups are `calm` (including `calm_1`, `calm_2`, etc.),
`dictation`, `scam`, and `intruder`. Calibration/enrollment and unknown
conditions are excluded from video processing. Labels
come from session metadata with a read-only SQLite fallback, not from filename
or execution order. Original condition and order index are preserved.

Each scenario is written to its own directory under `data/derived_video/`:

- `calm/frames.jsonl`, `dictation/frames.jsonl`, `scam/frames.jsonl`, and
  `intruder/frames.jsonl`: one file per scenario containing all exported frames with video-relative timestamps, estimated BPM, pulse window length,
  facial blendshape scores, full face landmarks, pose landmarks with visibility,
  and shoulder/head tilt and head-to-shoulder ratio.
- `manifest.csv` in each scenario directory records every session, its source
  status, and whether it was processed or failed.
- `summary.json` records per-scenario totals and failures.

Each frame includes its `session_id`, original `condition`, and `order_index`,
so feature rows remain attributable to the source session without participant
codes. Re-running a scenario replaces that scenario's three output files.
Repeated video timestamps are skipped, and
their count appears in the completion summary printed to the terminal;
backward timestamps still fail that recording rather than silently misaligning
measurements.

The inventory command groups references without copying or changing recordings.
MediaRecorder chunks are joined byte-for-byte in numeric order in temporary
storage before PyAV decoding. Missing chunks and unfinished sessions are skipped;
`--include-incomplete` enables unfinished sessions with contiguous chunks.
Sessions without video cannot be reconstructed, even if live landmarks exist.
Use an output directory outside the input sessions directory.

The pulse pipeline reuses `Processor` from the local live-analysis repository
at `/workspace/hackyeah/HackYeach-2026-REPO`, with its PhysNet checkpoint.
Override with `--live-root` or `--weights`. MediaPipe uses the same model assets
and blendshape/pose definitions as the browser. Facial and posture features are
exported at 5 Hz (`--feature-fps`); pulse processing receives every decoded frame.
The GPU processes temporal windows in sequence to preserve pulse-history
alignment; increasing the batch arbitrarily would change that signal and can
increase memory use without improving the CPU-bound MediaPipe steps. Each worker
is limited to four PyTorch/BLAS threads to avoid oversubscribing the 18 CPU cores.
Pulse state restarts for each session. BPM stays null until at least five seconds
of pulse history are available. Estimates are experimental camera-based pulse
measurements, not ECG, individual heartbeat timestamps, or emotion ground truth.
Posture values describe geometry; no uncalibrated slouching diagnosis is made.
Video seconds are relative to the first presentation timestamp, not the server's
session creation time. The recorder does not persist an exact wall-clock time for
the first video frame, so exact alignment to browser event timestamps is unavailable.

For a short validation of one recording:

```bash
/venv/main/bin/python scripts/extract_video_data.py \
  --group calm --session SESSION_ID --max-seconds 12 --device cuda:0 --output /tmp/video-check
```

Partial-output counts are printed when extraction finishes. Use a separate output folder
for subsets/smoke tests. Re-running a group replaces that scenario's output files.
Original recordings remain untouched.
Dependencies are the live server's environment: torch, numpy, scipy, opencv,
av, mediapipe, aiohttp, and aiortc. No web service is started.
