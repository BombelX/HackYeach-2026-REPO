"""Bridge completed video preprocessing to the deployed session-risk model."""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

try:
    import storage
except ModuleNotFoundError:
    from server import storage


REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_ROOT = Path(os.environ.get("PROCESSED_DATA_DIR", REPO_ROOT / "data" / "processed"))


def _session_details(session_id: str) -> dict[str, str] | None:
    conn = storage.connect()
    row = conn.execute(
        """SELECT s.condition, p.code AS participant_code, p.victim_code
           FROM sessions s JOIN participants p ON p.id=s.participant_id
           WHERE s.id=?""",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row is not None else None


def processed_session_dir(session_id: str) -> Path | None:
    """Return a completed extractor output, regardless of its condition group."""
    sessions = PROCESSED_ROOT / "sessions"
    if not sessions.is_dir():
        return None
    matches = sorted(sessions.glob(f"*/{session_id}"))
    return matches[0] if matches else None


def _live_video_score(session_id: str) -> int:
    """Produce an immediate 0–100 score from the camera features recorded so far.

    The full fusion checkpoint is preferred below when extracted features exist.
    During a live transfer, its 10-second feature windows are not available yet,
    so this reads the same MediaPipe video features that the recorder has already
    posted for the current payment form.
    """
    path = storage.SESSIONS_DIR / session_id / "face.jsonl"
    samples: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                shapes = row.get("blendshapes") or {}
                if shapes:
                    samples.append(shapes)
            except (TypeError, ValueError):
                continue
    if not samples:
        return 0

    def mean(name: str) -> float:
        values = [float(s.get(name, 0.0)) for s in samples]
        return sum(values) / len(values)

    # Stress/pressure-related facial-action units from the live video stream.
    tension = (
        0.26 * (mean("browDownLeft") + mean("browDownRight")) / 2
        + 0.22 * (mean("eyeWideLeft") + mean("eyeWideRight")) / 2
        + 0.20 * (mean("eyeSquintLeft") + mean("eyeSquintRight")) / 2
        + 0.20 * (mean("mouthPressLeft") + mean("mouthPressRight")) / 2
        + 0.12 * mean("jawOpen")
    )
    return max(0, min(100, round(100 * tension)))


def assess_session(session_id: str) -> dict[str, Any]:
    """Return a score immediately, preferring the full model when available."""
    details = _session_details(session_id)
    if details is None:
        raise KeyError(session_id)

    profile = details["victim_code"] if details["condition"] == "intruder" else details["participant_code"]
    processed = processed_session_dir(session_id)
    if processed is None or not profile:
        return {"status": "scored", "session_id": session_id, "score": _live_video_score(session_id)}

    # Import lazily: the collection API remains usable on installations that do not
    # include the optional PyTorch inference stack.
    from training.inference_xgb_suspicious import predict_suspicious

    try:
        result = predict_suspicious(processed, profile)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError, OSError):
        return {"status": "scored", "session_id": session_id, "score": _live_video_score(session_id)}
    return {
        "status": "scored",
        "score": max(0, min(100, round(100 * float(result["review_score"])))),
        "processed_session": str(processed),
        **result,
    }
