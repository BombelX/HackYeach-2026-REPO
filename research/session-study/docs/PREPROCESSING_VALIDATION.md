# Processing results — 2026-10-03

Outputs in `data/processed/` contain Parquet/JSON and context only, without videos
or image frames. Source recordings were unchanged. Validated output size was
approximately 955 MB.

## Dataset coverage

Of 201 inspected sessions, 108 were processed: calm 39, dictation 27, intruder 21,
scam 21. They contain 84 videos totaling 13,937.028 seconds; 24 video-free sessions
retain keyboard, mouse and context. Stable snapshots of nine unclosed sessions
were included. Explicit skips: 62 calibrations, 25 withdrawn sessions and six
incomplete chunk sets. See [source issues](INPUT_ISSUES.md). Missing data was not
filled with chunks from other sessions.

| Table | Rows |
| --- | ---: |
| keyboard | 7,963 |
| keyboard_events | 16,351 |
| keyboard_windows | 1,039 |
| mouse | 360,286 |
| network | 49,542 |
| markers | 22,000 |
| frames | 69,652 |
| pulse | 418,155 |
| pulse_windows | 4,388 |
| timeline | 69,730 |
| browser_face | 212,399 |

`sessions.parquet` includes all 201 sessions with skip reasons, labels, participant
IDs and availability masks. Mouse exists in 108 sessions, video in 84, HR/face/pose
in 83. One video has no valid face/pose detection.

Keyboard inference used original Aalto features, windows up to 96 presses and
masks. The actual model returns 128D, not 96D. Profiles exist for 68 sessions.
The other 40 lack keys or valid segments of at least 16 presses; short segments
are retained with false masks rather than fabricated embeddings. Of 1,039 saved
segments, 143 have valid window embeddings. No mouse model was trained or run.

## Synchronization and estimates

All 84 videos use `approx_session_start`: the recorder did not save an exact start
anchor, so server alignment has an explicit uncertainty interval. Chunk upload time
was never treated as exact frame time. The new recorder saves a start-request
anchor for future recordings.

Pulse/BPM comes from pretrained PhysNet camera estimation without reference ECG.
Detection gaps remain null; numeric interpolation is bounded and masked. Parallel
parts of long videos have explicit model-history boundaries; amplitudes must not
be joined for HRV.

## Tests and review

- 61 unit/regression tests passed, including 14 parallel-extraction tests and five stale-cache rejection tests.
- Keyboard architecture matches training-code output; preprocessing of the first 512 Aalto samples is bit-identical.
- TypeScript `tsc --noEmit` and Vite build passed after recorder-anchor changes.
- The data validator checked 108 sessions/201 index rows with no errors: sources, artifact sizes, counts, monotonicity, missing-signal masks, profile dimensions and norms.
- CLI resume reported 108 resumed, zero queued, without recomputing data. Its sub-second duration covers only final reports/indexes, not full extraction.
- Independent review covered clocks, Aalto features, mouse events, rPPG, model masks, segment coverage and atomic publishing. Fixes included optional Arrow columns, pulse-window boundaries, new-chunk checks and queue shutdown on interruption.

Machine report: `data/processed/validation.json`. Run/skip details:
`run_report.json`, `run_summary.json`, `inventory.json`. Long-video coverage:
per-session `parallel_validation.json`.

## Resources

The full run used 32 workers across four RTX 5090 GPUs: about 43 CPU cores, 62 GiB
RSS and 15–17 GiB VRAM per GPU, without OOM. MediaPipe/decoding were the bottleneck;
PhysNet peaked near 0.916 GB allocated per worker. The final long video used
16 parallel parts on four GPUs and reached 24.09× realtime with coverage checks.
See [commands and methods](PREPROCESSING.md).

The instance had no host volume. Copy local results off-instance before recycle
or destruction.
