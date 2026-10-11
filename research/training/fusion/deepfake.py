"""Optional, uncalibrated image-forensics signal from sampled video frames."""
from __future__ import annotations

from pathlib import Path
import random

import numpy as np

from preprocessing.sessions import concatenate_chunks

MODEL_ID = "prithivMLmods/Deep-Fake-Detector-v2-Model"
MODEL_REVISION = "3a99ae26f52c7ac7c3a53103b6cf3a8b617f7093"
MAX_FRAMES = 16


def score_frames(frames, processor, model, device: str) -> dict:
    """Return a diagnostic score, not a calibrated deepfake probability."""
    import torch

    labels = model.config.id2label
    fake = [int(k) for k, v in labels.items() if str(v).lower() == "deepfake"]
    if len(fake) != 1 or len(labels) != 2:
        raise ValueError(f"Unsupported deepfake model labels: {labels}")
    if not frames:
        return {"status": "unavailable", "reason": "no_decodable_frames", "frames_scored": 0}
    x = processor(images=frames, return_tensors="pt")
    with torch.inference_mode():
        logits = model(**{k: v.to(device) for k, v in x.items()}).logits
        values = logits.softmax(dim=-1)[:, fake[0]].cpu().numpy()
    if len(values) != len(frames) or not np.isfinite(values).all():
        raise ValueError("Invalid deepfake model output")
    return {
        "status": "scored_unvalidated",
        "model": f"{MODEL_ID}@{MODEL_REVISION}",
        "frames_scored": len(frames),
        "fake_frame_score_median": float(np.median(values)),
        "fake_frame_score_max": float(np.max(values)),
        "fake_frame_score_p90": float(np.percentile(values, 90)),
        "interpretation": "image-model diagnostic only; not calibrated for webcam video or liveness",
    }


def sample_frames(video: Path, max_frames: int = MAX_FRAMES) -> list:
    import av
    from PIL import Image

    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    frames = []
    with av.open(str(video)) as container:
        if not container.streams.video:
            raise ValueError(f"No video stream in {video}")
        stream = container.streams.video[0]
        duration = (float(stream.duration * stream.time_base) if stream.duration
                    else float(container.duration / av.time_base) if container.duration else None)
        if duration is None or duration <= 0:
            # MediaRecorder WebM often lacks duration metadata; sample across the
            # entire recording without holding decoded frames in memory.
            rng = random.Random(0)
            candidates = 0
            last_second = float("-inf")
            for frame_index, frame in enumerate(container.decode(video=0)):
                second = frame.time if frame.time is not None else frame_index / float(stream.average_rate or 30)
                if second < last_second + 1:
                    continue
                last_second = second
                candidates += 1
                slot = candidates - 1 if candidates <= max_frames else rng.randrange(candidates)
                if slot < max_frames:
                    image = Image.fromarray(frame.to_ndarray(format="rgb24"))
                    if slot == len(frames):
                        frames.append(image)
                    else:
                        frames[slot] = image
        else:
            # Seek into distinct parts of the recording rather than processing every frame.
            for second in np.linspace(0.5, max(0.5, duration - 0.5), max_frames):
                timestamp = int(max(0, second - 0.5) / float(stream.time_base))
                container.seek(timestamp, stream=stream, backward=True)
                for frame in container.decode(video=0):
                    if frame.time is not None and frame.time + 0.1 < second:
                        continue
                    frames.append(Image.fromarray(frame.to_ndarray(format="rgb24")))
                    break
    return frames


def crop_faces(frames: list) -> list:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    from preprocessing.vision import VisionConfig, face_box

    model_path = Path(VisionConfig().face_model)
    if not model_path.is_file():
        raise FileNotFoundError(f"MediaPipe face detector not found: {model_path}")
    options = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.IMAGE, num_faces=1)
    crops = []
    with vision.FaceLandmarker.create_from_options(options) as detector:
        for frame in frames:
            rgb = np.asarray(frame.convert("RGB"))
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not result.face_landmarks:
                continue
            box = face_box(result.face_landmarks[0], rgb.shape[1], rgb.shape[0], 1.5)
            if box is not None:
                crops.append(frame.crop(box))
    return crops


def score_video(video: Path, *, device: str | None = None, max_frames: int = MAX_FRAMES) -> dict:
    import torch

    try:
        from transformers import ViTForImageClassification, ViTImageProcessor
    except ImportError as exc:
        raise RuntimeError("Install optional dependency: /venv/main/bin/python -m pip install 'transformers>=4.49,<5'") from exc
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    frames = sample_frames(video, max_frames=max_frames)
    if not frames:
        return {"status": "unavailable", "reason": "no_decodable_frames", "frames_scored": 0}
    faces = crop_faces(frames)
    if not faces:
        return {"status": "unavailable", "reason": "no_face_detected",
                "frames_sampled": len(frames), "frames_scored": 0}
    processor = ViTImageProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False)
    model = ViTForImageClassification.from_pretrained(
        MODEL_ID, revision=MODEL_REVISION, use_safetensors=True).to(device).eval()
    result = score_frames(faces, processor, model, device)
    result["frames_sampled"] = len(frames)
    return result


def score_session_video(session_id: str, *, source_root: Path, device: str | None = None) -> dict:
    """Score local recorder chunks; never upload source video or modify it."""
    from tempfile import TemporaryDirectory

    video_dir = source_root / session_id / "video"
    chunks = sorted(video_dir.glob("*.webm"))
    if not chunks:
        return {"status": "unavailable", "reason": "no_source_video", "frames_scored": 0}
    with TemporaryDirectory(prefix="fusion-deepfake-") as tmp:
        video = concatenate_chunks(chunks, Path(tmp) / "joined.webm")
        return score_video(video, device=device)


def assess_video(session: str | Path, video: Path | None = None) -> dict:
    from training.fusion.features import ROOT

    if video is not None:
        return score_video(video)
    return score_session_video(Path(session).name, source_root=ROOT / "data" / "sessions")
