# Multimodal pipeline — working plan

Process complete calm, dictation, scam and intruder recordings into numeric session
data on one timeline. Preserve source recordings for verification; archive them
off-server only after confirming output completeness.

## Repository findings

- Historical dataset: `/workspace/hackaton/HackYeach-2026-REPO/data/sessions`. Synchronization may add files. Default processing accepts completed sessions and continuous numbered container chunks.
- The browser records `performance.now()` milliseconds, `Date.now()` and clock-sync offset/RTT; the server uses Unix seconds. `FaceFrame.video_ts` is performance time, not video PTS.
- Old recordings lack an exact first-frame/browser-clock anchor. Outputs must state synchronization uncertainty. New recordings need a MediaRecorder-start marker.
- MediaRecorder chunks form one container: concatenate bytes in index order. Do not decode each chunk independently or assume five seconds per chunk.
- Historical hardware: four RTX 5090s, torch 2.11/CUDA 12.8. Assign each worker a GPU and use a shared session queue.
- PhysNet UBFC-rPPG and MediaPipe face/pose are available. Vision/decode run on CPU; neural rPPG and keyboard inference on GPU.
- Keyboard inference accepts 16–96 presses and eight precisely defined features. Existing weights return 128D; 96 is not embedding dimension. Do not arbitrarily change trained weights.

## Implementation

1. Inventory all sessions, conditions, statuses, sources, sizes and fingerprints. Add preprocessing modules without overwriting platform changes or the old extractor.
2. Separate clock/bounded-resampling, events/keyboard/mouse and reusable VisionExtractor modules.
3. Decode RGB once, preserve PTS, sample face/pose less often and crop rPPG input. Bound buffers by window size. Write landmarks, blendshapes, posture geometry, pulse, HR and quality.
4. Write per-session Parquet plus JSON context (metadata, survey, net/HAR). Retain keyboard order and masked 128D embeddings; extract mouse numbers/timestamps without training.
5. Build a common timeline with observation/interpolation/extrapolation masks and maximum gaps. Never replace missing data with zeros. Retain keyboard/mouse events independently.
6. Use a dynamic four-GPU queue, spawn without inherited CUDA, CPU thread limits, atomic session publication, fingerprint-based resume, writer locks and per-session failure isolation.

## Verification

Test time conversion, gaps/extrapolation, key pairing, Aalto preprocessing and
checkpoint loading. Integrate real recordings from every condition, benchmark
GPU/CPU, then extract the full dataset and validate inventory/output coverage.
Review synchronization, memory growth, resume/atomicity, missing modalities and
weight compatibility.
