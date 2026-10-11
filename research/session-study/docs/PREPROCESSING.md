# Session data extraction

The pipeline processes recorded `calm`, `dictation`, `scam` and `intruder` sessions.
It does not train a new model. Results are Parquet/JSON without image frames or
video copies; source recordings remain available for verification. See the
[implementation plan](PREPROCESSING_PLAN.md).

## Running

From `research/session-study/`, using an environment with the research dependencies:

```bash
python scripts/preprocess_sessions.py --inventory-only
python scripts/preprocess_sessions.py
python scripts/preprocess_sessions.py --include-incomplete --workers-per-gpu 8
```

The historical production instance had four RTX 5090 GPUs. Eight workers per GPU
started 32 workers, using about 43 CPU cores, 62 GiB RSS and 15–17 GiB VRAM per GPU
without OOM. Adapt concurrency to your hardware; the default two workers per GPU
requires less memory.

Defaults: GPUs 0,1,2,3, two CPU/GPU workers per card, output `data/processed`.
A shared session queue gives each available worker the next session; GPUs are not
assigned to conditions. `--workers-per-gpu 1` limits concurrency, `--gpu-ids 0 1`
limits devices, and `--cpu` uses one non-CUDA worker.

Only completed sessions are processed by default. `--include-incomplete` captures
a stable snapshot of unclosed sessions and preserves their source status.
Calibration, withdrawn participants and invalid chunk sets get explicit skip
reasons in inventory/run_report. Sessions without video retain other modalities
and empty video tables.

Use a separate output for a short trial:

```bash
python scripts/preprocess_sessions.py \
  --session SESSION_ID --max-seconds 30 --output /tmp/preprocessing-check
```

`--max-seconds` limits only video extraction; logs and embeddings cover the whole
session. Summaries record `truncated_run` and `video.truncated`. Omit it for a full
run. Reruns skip complete outputs with matching source/code/configuration/weight
fingerprints. `--force` recomputes. Incomplete output or changed sources/models
require reprocessing. Publication occurs only after all tables complete. One
session error does not stop others; failures produce a nonzero exit code. An output
directory lock prevents concurrent writers.

## Output format

Each session has `data/processed/sessions/<group>/<session_id>/`:

| File | Contents |
| --- | --- |
| `frames.parquet` | PTS, 478 face landmarks, blendshapes, 33 pose/world landmarks, posture geometry and detection masks; target 5 Hz |
| `pulse.parquet` | PhysNet differential/integrated signal, BPM, quality descriptions, segments and source interpolation; 30 Hz |
| `pulse_windows.parquet` | Neural window bounds, coverage/padding, separate extraction/synchronization statuses |
| `timeline.parquet` | Shared 5 Hz grid: face/pose/pulse scalars, masks and keyboard/mouse counts |
| `keyboard.parquet` | Press/release times, eight training features, numeric IDs and masks |
| `keyboard_events.parquet` | All keydown/keyup events, including repeats, without typed characters |
| `keyboard_windows.parquet` | Up to 96 presses per window, input mask and 128D embeddings |
| `mouse.parquet` | Pointer/click/wheel/scroll samples, coalesced timestamps, coordinates and device attributes |
| `network.parquet` | Clock sync, ping, requests, environment and other network data in `payload_json` |
| `markers.parquet` | Stages and other events, excluding typed field contents |
| `browser_face.parquet` | Original browser numeric face/pose measurements on a unified clock |
| `context.json` | Metadata, DB, survey, feature definitions, field maps, keyboard profile and synchronization |
| `summary.json` | Artifact manifest, configuration, fingerprint, row counts and statistics |

Additional context, including nested HAR files, is retained in `extra_context`.
The current dataset has request/ping logs and environment metadata, but no HAR;
the pipeline does not invent missing files.

Top-level `inventory.json`, `run_report.json`, `run_summary.json` describe the
inventory/run. `sessions.parquet` links profiles, labels, modality masks and tables
for training. Participant IDs support person-level splits. Scenario labels and
surveys remain labels/context, not keyboard-embedding inputs.

## Time and missing data

`t_session_ms` measures milliseconds from server session start.
`t_server_epoch_ms` is synchronized Unix milliseconds; original client clocks
and video PTS are also retained. Low-RTT clock-sync samples map the monotonic
client clock with a fixed offset, avoiding network-jitter distortion of typing rhythm.

The old recorder did not save MediaRecorder start time. `face.video_ts` was
`performance.now()`, while chunk uploads record server receipt. Neither gives an
exact first-frame PTS. Old sessions use `approx_session_start` with an explicit
uncertainty interval. New `camera.recording_clock` provides
`recording_start_requested`; unknown first-encoded-frame latency remains explicit.
Chunks are joined bytewise and decoded through PTS, never assigned arbitrary
five-second durations.

The grid interpolates numeric signals only between valid observations, normally
across gaps up to 500 ms. Explicit missing detections and longer gaps stay null.
`--max-extrapolation-ms` enables bounded edge extrapolation with a separate mask;
default is zero. Scalars have `valid`, `observed`, `interpolated`, `extrapolated`
masks. Keyboard/mouse events are never synthesized. Full landmarks keep their
own timestamps in `frames.parquet`; the grid holds scalar summaries.

## Models and performance

PhysNet uses `UBFC-rPPG_PhysNet_DiffNormalized.pth`, 72×72 RGB crops, 30 Hz,
128-frame windows, stride 96 and batch 8. It runs on GPU; MediaPipe face/pose and
decoding use CPU. RGB is decoded once and image buffers are bounded by batch/window.

BPM is a spectral estimate requiring at least five seconds of valid signal in the
45–150 BPM band. Spectral concentration describes energy distribution, not
calibrated confidence. Offline output uses complete windows and is not causal
online inference. Pulse amplitude is relative. Do not join segments separated by
missing detections for HRV or interpret them as real heartbeat timestamps.
Accuracy requires independent reference-sensor evaluation.

The historical `/workspace/keystroke_long_epoch_59.pt` keyboard checkpoint produces
**128D**. **96 is sequence length, not profile dimension**. Trained dimensions were
not changed. See [keyboard/mouse preprocessing](../preprocessing/KEYBOARD_MOUSE.md).
The mouse model is neither trained nor run by this extraction pipeline.

A four-worker/four-RTX-5090 benchmark processed 120 video seconds in 20.83 seconds
including spawn, or 5.76× realtime, at about 0.916 GB model memory per GPU.
CPU decoding/MediaPipe are the main bottleneck; extra workers increase concurrency.
Filling VRAM or reaching 100% GPU is not the objective. Use `video_summary.json`
to tune settings.

### Long recordings

`scripts/parallel_long_video.py` remuxes VP8/VP9 into indexed MKV without re-encoding,
verifying PTS/keyframe flags. It splits into 307.2-second parts with 16-second
warmup and 12.8-second lookahead, then writes disjoint parts on one global grid.
Outputs retain real PTS; technical warmup anchors are excluded. Coverage checks
reject missing/duplicate samples and incomplete internal-boundary windows.

```bash
python scripts/parallel_long_video.py \
  --video /path/to/joined.webm --output /tmp/long-video-cache --workers 16
```

After verifying cache, `scripts/finish_cached_session.py` performs normal atomic
table publication and synchronization. `--template-summary` must point to a
session processed with identical settings/weights. Source video, model/code hashes,
configuration and all cache files must match the coverage report. A normal pipeline
run can then rebuild reports/indexes without recalculating completed tables.

```bash
python scripts/finish_cached_session.py --session SESSION_ID \
  --cache /tmp/long-video-cache \
  --template-summary data/processed/sessions/calm/OTHER_SESSION/summary.json
```

Face/pose trackers and model history are independent between parts. Warmup provides
BPM context, but coordinates may differ from a serial run. `model_history_segment_id`
and globally unique `pulse_segment_id` mark boundaries. The first `pulse_value` in
a part is null to prevent interpolation between independent integration baselines.
`pulse_valid` can remain true for valid differential signal/BPM while
`pulse_value_valid` is false. `parallel_provenance` and summaries record the method
and helper hash.

A full 5,066.628-second recording processed in 210.29 seconds with 16 workers/four
GPUs, including remux/merge: 24.09× realtime. Coverage verified 84,217 unique
frames, 25,334 5 Hz measurements and 151,999 30 Hz samples with no index gaps.
Final conversion, synchronization and Parquet writing took another 106.46 seconds.

## Verification

```bash
python -m unittest discover -s tests -v
python scripts/validate_processed.py
```

Tests cover clocks, PTS/anchors, missing detection, bounded resampling, WebM/MP4
chunks, masks, Aalto features, missing keyup, repeats, coalesced pointer samples,
optional-column preservation and atomic output. TypeScript/Vite passed after the
recorder-anchor change. Integration used a real recording from each condition.
See [validation results](PREPROCESSING_VALIDATION.md).

Session schemas can contain null types for entirely absent modalities. Union/cast
schemas for aggregate reads, or follow the per-session paths in `sessions.parquet`.
The historical instance had no host volume: copy local results off-instance before
recycle/destroy.
