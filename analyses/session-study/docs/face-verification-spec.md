# Face verification

The original requested specification was not present in the checkout. This
document records the implementation contract agreed from the task description
and the actual collector payload (`face_key`: 43 selected MediaPipe landmarks;
`blendshapes`: 52 values).

## Signals and consent

- `consents.face_pose` is required before Face-B processing and enrollment.
- Face-A additionally requires `consents.video`.
- A request without the required consent returns `no_consent`; it must not
  persist submitted landmarks or create face embeddings.
- Enrollment uses only `calm*` sessions. Intruder sessions are negative
  calibration examples, never enrollment examples.
- Face artifacts are stored under `data/processed/models/face/` with directory
  mode `0700` and files mode `0600`. Deleting a participant removes their
  enrollment/probe embeddings and invalidates aggregate thresholds.

## Face-B (continuous)

- The `/face` JSON payload is scored synchronously after it is appended.
- Each landmark vector is translated to the midpoint of MediaPipe eye points
  33/263, rotated to the eye line, and scaled by inter-eye distance. The
  normalized 3-D geometry is concatenated with the observed blendshape vector
  scaled by `0.25`; the combined vector is L2-normalized.
- The profile is the normalized mean of per-calm-session normalized means,
  giving each calm session equal weight. Frame cosine scores are reduced to
  the median for the received batch. Missing faces remain unavailable.
- `face_calibrate.py --modality b` compares a calm enrollment profile that
  excludes the evaluated calm session against calm/scam/dictation positives
  and intruder negatives. The equal-error-rate operating threshold is
  exploratory and is not an automatic account block.

## Face-A (sampled)

- Optional InsightFace `buffalo_l` produces aligned, normalized 512-D
  embeddings. CPU inference is the default fallback; ONNX Runtime CUDA is used
  when available unless `FACE_USE_GPU=0`.
- Face-A is local-only at runtime by default: all five `buffalo_l` ONNX files
  must be provisioned in `~/.insightface/models/buffalo_l`. If unavailable, a
  background task records `model_unavailable` without affecting the upload.
  Set `FACE_A_ALLOW_MODEL_DOWNLOAD=1` only in a controlled provisioning job
  that is allowed to download model weights.
- The video-upload route only schedules a FastAPI `BackgroundTasks` job after
  writing the chunk. Normal sampling scores one frame from the newest
  `video/*.webm` chunk per upload (the target cadence defaults to five seconds
  via `FACE_SAMPLE_INTERVAL_S`). A low Face-B match samples up to two frames.
  MediaRecorder chunks after the first may not be standalone WebM files. If
  the newest chunk is not independently decodable, the sampler uses FFmpeg's
  zero-copy concat protocol and seeks to the final `video_ts`; it decodes only
  the nearby keyframe pre-roll and evaluates 1–2 selected frames. It never
  walks the whole recording with the face model.
- Face-A enrollment samples up to two frames from the last chunk of each
  consented calm session. Probe/calibration embeddings are stored in
  `face_a_embeddings.parquet`.
- `face_calibrate.py --modality a` samples one frame from each consented
  session with video; positive sessions are non-intruder, negative sessions
  are intruder. It uses leave-one-session-out enrollment prototypes.

## API and operation

`GET /api/sessions/{id}/risk` returns `score_b`, `score_a`, calibrated
thresholds, calibration reliability, status and `escalation`. A score can
escalate only when it falls below a threshold whose held-out calibration has
enough examples and useful separation (AUC >= 0.70; FAR/FRR <= 25%). A weak
study calibration remains visible as telemetry but fails closed: it cannot
silently become an account-blocking rule. Set
`FACE_ALLOW_EXPLORATORY_ESCALATION=1` only for a supervised experiment.
Missing consent, missing profile, missing detection and missing calibration are
explicit states; they are not converted to a match or mismatch.

```bash
/venv/main/bin/python scripts/face_build_enroll.py --data-dir data
/venv/main/bin/python scripts/face_calibrate.py --data-dir data --modality b
/venv/main/bin/python -m pip install -r server/requirements-face.txt
/venv/main/bin/python scripts/face_build_enroll.py --data-dir data --face-a
/venv/main/bin/python scripts/face_calibrate.py --data-dir data --modality a
/venv/main/bin/python scripts/face_verify_session.py <session_id>
```

Install `onnxruntime-gpu` in place of the CPU `onnxruntime` package to enable
CUDA in an environment with compatible ONNX Runtime/CUDA libraries. GPU is
optional. Calibration uses the existing small study set and is for evaluation
only; deployment needs additional consented and independently labeled
same-owner device/location changes, intruders and presentation attacks.
