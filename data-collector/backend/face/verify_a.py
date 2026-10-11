from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import numpy as np

_app = None
_app_lock = threading.Lock()


class VideoChunkDecodeError(RuntimeError):
    pass


class FaceModelUnavailable(RuntimeError):
    """The optional Face-A model is not available locally."""


def _require_local_model() -> None:
    """Avoid a surprise model download from a request background task.

    A deployment can opt into InsightFace's download behaviour explicitly with
    ``FACE_A_ALLOW_MODEL_DOWNLOAD=1`` during provisioning.  Runtime defaults
    to local-only operation so a network outage remains a clean degradation.
    """
    if os.environ.get("FACE_A_ALLOW_MODEL_DOWNLOAD") == "1":
        return
    home = Path(os.environ.get("INSIGHTFACE_HOME", "~/.insightface")).expanduser()
    model_dir = home / "models" / "buffalo_l"
    required = {"1k3d68.onnx", "2d106det.onnx", "det_10g.onnx", "genderage.onnx", "w600k_r50.onnx"}
    missing = sorted(name for name in required if not (model_dir / name).is_file())
    if missing:
        raise FaceModelUnavailable(
            "Face-A buffalo_l is not provisioned locally; missing " + ", ".join(missing)
        )


def get_face_analysis():
    global _app
    with _app_lock:
        if _app is None:
            try:
                from insightface.app import FaceAnalysis
            except ImportError as exc:
                raise RuntimeError(
                    "Face-A requires InsightFace; install server/requirements-face.txt"
                ) from exc
            import onnxruntime as ort

            _require_local_model()
            providers = ort.get_available_providers()
            preferred = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            _app = FaceAnalysis(name="buffalo_l", providers=[p for p in preferred if p in providers])
            use_gpu = "CUDAExecutionProvider" in providers and os.environ.get("FACE_USE_GPU", "auto") != "0"
            _app.prepare(ctx_id=0 if use_gpu else -1, det_size=(640, 640))
        return _app


def normalize_embedding(embedding) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.shape != (512,) or not np.isfinite(vector).all():
        raise ValueError("InsightFace returned an invalid embedding")
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        raise ValueError("InsightFace returned an empty embedding")
    return vector / norm


def embed_chunk(path: Path, *, max_frames: int = 2) -> list[np.ndarray]:
    import av

    if max_frames < 1 or max_frames > 3:
        raise ValueError("max_frames must be between 1 and 3")
    model = get_face_analysis()
    embeddings = []
    try:
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise VideoChunkDecodeError(f"No video stream in {path}")
            stream = container.streams.video[0]
            target_times = (0.0,) if max_frames == 1 else (0.2, 0.8)[:max_frames]
            next_target = 0
            fps = float(stream.average_rate) if stream.average_rate else 30.0
            for frame_index, frame in enumerate(container.decode(video=0)):
                seconds = float(frame.time) if frame.time is not None else frame_index / fps
                if seconds + 1e-6 < target_times[next_target]:
                    continue
                bgr = frame.to_ndarray(format="bgr24")
                detected = model.get(bgr)
                if detected:
                    embeddings.append(normalize_embedding(max(detected, key=lambda face: face.det_score).embedding))
                next_target += 1
                if next_target >= len(target_times):
                    break
    except av.error.FFmpegError as exc:
        raise VideoChunkDecodeError(f"Could not decode video chunk {path}: {exc}") from exc
    return embeddings


def _face_video_time_range(face_path: Path) -> tuple[float, float] | None:
    if not face_path.is_file():
        return None
    first = None
    with face_path.open("rb") as stream:
        for _ in range(128):
            line = stream.readline()
            if not line:
                break
            try:
                value = float(json.loads(line).get("video_ts"))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
            if np.isfinite(value):
                first = value
                break
        if first is None:
            return None
        size = stream.seek(0, os.SEEK_END)
        read_size = min(size, 1 << 20)
        stream.seek(size - read_size)
        lines = stream.read().splitlines()
    last = None
    for line in reversed(lines):
        try:
            value = float(json.loads(line).get("video_ts"))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if np.isfinite(value):
            last = value
            break
    return (first, last) if last is not None and last >= first else None


def _embed_joined_tail(session_dir: Path, max_frames: int) -> list[np.ndarray]:
    import av

    model = get_face_analysis()
    chunks = sorted(session_dir.glob("video/*.webm"), key=lambda p: p.name)
    indexes = [int(path.stem) for path in chunks if path.stem.isdecimal()]
    if len(indexes) != len(chunks) or indexes != list(range(len(chunks))):
        raise VideoChunkDecodeError(f"Video chunks are not contiguous for {session_dir.name}")
    time_range = _face_video_time_range(session_dir / "face.jsonl")
    if time_range is None:
        raise VideoChunkDecodeError(f"No reliable video_ts range for {session_dir.name}")
    target = (time_range[1] - time_range[0]) / 1000.0
    if target < 0:
        raise VideoChunkDecodeError(f"Invalid video_ts range for {session_dir.name}")
    encoded_paths = [str(path).replace("\\", "\\\\").replace("|", "\\|") for path in chunks]
    url = "concat:" + "|".join(encoded_paths)
    try:
        with av.open(url, format="webm") as container:
            if not container.streams.video:
                raise VideoChunkDecodeError(f"No video stream in {session_dir}")
            stream = container.streams.video[0]
            targets = np.linspace(max(0.0, target - 0.8), max(0.0, target - 0.2), max_frames)
            container.seek(int(max(0.0, target - 1.5) / float(stream.time_base)),
                           stream=stream, backward=True)
            embeddings = []
            next_target = 0
            for frame in container.decode(video=0):
                seconds = float(frame.time) if frame.time is not None else None
                if seconds is None:
                    continue
                if seconds > target + 0.5:
                    break
                if seconds + 1e-6 < targets[next_target]:
                    continue
                detected = model.get(frame.to_ndarray(format="bgr24"))
                if detected:
                    embeddings.append(normalize_embedding(max(detected, key=lambda face: face.det_score).embedding))
                next_target += 1
                if next_target == len(targets):
                    break
    except av.error.FFmpegError as exc:
        raise VideoChunkDecodeError(f"Could not seek to last video frames for {session_dir.name}: {exc}") from exc
    return embeddings


def embed_latest_session_chunk(session_dir: Path, *, max_frames: int = 2) -> tuple[Path | None, list[np.ndarray]]:
    chunks = sorted(session_dir.glob("video/*.webm"), key=lambda p: p.name)
    if not chunks:
        return None, []
    latest = chunks[-1]
    try:
        embeddings = embed_chunk(latest, max_frames=max_frames)
        if embeddings:
            return latest, embeddings
    except VideoChunkDecodeError:
        pass
    embeddings = _embed_joined_tail(session_dir, max_frames)
    return latest, embeddings


def similarity(embeddings: list[np.ndarray], profile: np.ndarray) -> float | None:
    if not embeddings:
        return None
    scores = np.asarray([float(np.dot(embedding, profile)) for embedding in embeddings])
    if not np.isfinite(scores).all():
        raise ValueError("Non-finite face-A cosine score")
    return float(np.median(scores))


def last_video_chunk(session_dir: Path) -> Path | None:
    paths = sorted(session_dir.glob("video/*.webm"), key=lambda p: p.name)
    return paths[-1] if paths else None
