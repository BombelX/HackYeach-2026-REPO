from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    import storage
except ModuleNotFoundError:
    from server import storage

from .enroll import append_face_a_rows, artifact_dir, load_profile_a, load_profile_b
from .features_b import cosine_scores, face_feature
from .verify_a import (FaceModelUnavailable, VideoChunkDecodeError,
                       embed_latest_session_chunk, last_video_chunk, similarity)

logger = logging.getLogger(__name__)


def _session(session_id: str) -> dict[str, Any] | None:
    conn = storage.connect()
    row = conn.execute(
        """SELECT s.id, s.condition, s.consents_json, p.code AS participant_code,
                  p.victim_code
           FROM sessions s JOIN participants p ON p.id=s.participant_id WHERE s.id=?""",
        (session_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    result = dict(row)
    result["consents"] = json.loads(result.pop("consents_json") or "{}")
    return result


def session_context(session_id: str) -> dict[str, Any] | None:
    return _session(session_id)


def _profile_code(session: dict[str, Any]) -> str:
    if session["condition"] == "intruder" and session.get("victim_code"):
        return session["victim_code"]
    return session["participant_code"]


def _risk_path(session_id: str) -> Path:
    return storage.SESSIONS_DIR / session_id / "face_verification.json"


def _state(session_id: str) -> dict[str, Any]:
    path = _risk_path(session_id)
    return json.loads(path.read_text()) if path.is_file() else {}


def _thresholds() -> dict:
    path = artifact_dir(storage.DATA_DIR) / "face_thresholds.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _persist(session_id: str, values: dict) -> dict:
    return storage.merge_json(session_id, "face_verification.json", values)


def update_face_b(session_id: str, rows: list[dict]) -> dict:
    session = _session(session_id)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    if not session["consents"].get("face_pose"):
        return _persist(session_id, {"b_status": "no_consent", "score_b": None, "samples_b": 0})
    profile_code = _profile_code(session)
    profile = load_profile_b(storage.DATA_DIR, profile_code)
    if profile is None:
        return _persist(session_id, {"b_status": "no_enrollment", "score_b": None, "samples_b": 0})
    reference, blendshape_names = profile
    vectors = [face_feature(row, blendshape_names) for row in rows]
    vectors = [vector for vector in vectors if vector is not None]
    if not vectors:
        return _persist(session_id, {"b_status": "no_face", "score_b": None, "samples_b": 0})
    scores = cosine_scores(np.stack(vectors), reference)
    valid = scores[np.isfinite(scores)]
    if not len(valid):
        return _persist(session_id, {"b_status": "no_face", "score_b": None, "samples_b": 0})
    threshold = _thresholds().get("face_b", {}).get("threshold")
    score = float(np.median(valid))
    return _persist(session_id, {
        "b_status": "scored",
        "score_b": score,
        "samples_b": int(len(valid)),
        "threshold_b": threshold,
        "score_b_updated_at": time.time(),
    })


def _below(value, threshold) -> bool:
    return value is not None and threshold is not None and float(value) < float(threshold)


def _escalation_ready(calibration: dict) -> bool:
    """Fail closed until the calibration data demonstrates useful separation."""
    return bool(calibration.get("eligible_for_escalation")) or (
        os.environ.get("FACE_ALLOW_EXPLORATORY_ESCALATION") == "1"
    )


def risk_for_session(session_id: str) -> dict:
    session = _session(session_id)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    state = _state(session_id)
    thresholds = _thresholds()
    face_consent = bool(session["consents"].get("face_pose"))
    video_consent = bool(session["consents"].get("video"))
    if not face_consent:
        return {
            "session_id": session_id, "status": "no_consent",
            "score_b": None, "score_a": None, "escalation": False,
            "threshold_b": thresholds.get("face_b", {}).get("threshold"),
            "threshold_a": thresholds.get("face_a", {}).get("threshold"),
        }
    calibration_b = thresholds.get("face_b", {})
    calibration_a = thresholds.get("face_a", {})
    reliable_b = _escalation_ready(calibration_b)
    reliable_a = _escalation_ready(calibration_a)
    tb = calibration_b.get("threshold")
    ta = calibration_a.get("threshold")
    score_b = state.get("score_b")
    score_a = state.get("score_a") if video_consent else None
    if state.get("b_status") == "no_consent":
        score_b = None
    if state.get("a_status") == "no_consent" or not video_consent:
        score_a = None
    reasons = []
    if reliable_b and _below(score_b, tb):
        reasons.append("face_b_below_threshold")
    if reliable_a and _below(score_a, ta):
        reasons.append("face_a_below_threshold")
    status = "ok"
    if not video_consent:
        status = "partial_no_video_consent"
    elif state.get("b_status") == "no_enrollment":
        status = "no_enrollment"
    elif state.get("b_status") == "no_face" and score_b is None:
        status = "awaiting_face"
    elif state.get("a_status") == "no_enrollment":
        status = "no_face_a_enrollment"
    elif (tb is not None and not reliable_b) or (video_consent and ta is not None and not reliable_a):
        status = "exploratory_calibration"
    elif not tb or (video_consent and state.get("a_status") != "scored" and not ta):
        status = "calibration_required"
    return {
        "session_id": session_id,
        "status": status,
        "score_b": score_b,
        "score_a": score_a,
        "threshold_b": tb,
        "threshold_a": ta,
        "calibration_b_reliable": reliable_b,
        "calibration_a_reliable": reliable_a,
        "escalation": bool(reasons),
        "escalation_reasons": reasons,
        "samples_b": state.get("samples_b", 0),
        "samples_a": state.get("samples_a", 0) if video_consent else 0,
        "updated_at": max(state.get("score_b_updated_at", 0), state.get("score_a_updated_at", 0)) or None,
    }


def process_video_chunk(session_id: str, uploaded_path: Path, chunk_index: int) -> dict:
    session = _session(session_id)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    consents = session["consents"]
    if not consents.get("face_pose") or not consents.get("video"):
        status = "no_consent"
        _persist(session_id, {"a_status": status, "score_a": None, "samples_a": 0})
        return {"status": status}
    profile_code = _profile_code(session)
    profile = load_profile_a(storage.DATA_DIR, profile_code)
    if profile is None:
        _persist(session_id, {"a_status": "no_enrollment", "score_a": None, "samples_a": 0})
        return {"status": "no_enrollment"}
    latest = last_video_chunk(storage.SESSIONS_DIR / session_id)
    if latest is None or latest != uploaded_path:
        uploaded_path = latest
    if not uploaded_path.is_file():
        return {"status": "no_video"}
    state = _state(session_id)
    if state.get("last_a_chunk") == uploaded_path.name:
        return {"status": "already_sampled"}
    thresholds = _thresholds()
    threshold_b = thresholds.get("face_b", {}).get("threshold")
    at_risk = _below(state.get("score_b"), threshold_b)
    interval = 1.0 if at_risk else float(os.environ.get("FACE_SAMPLE_INTERVAL_S", "5"))
    elapsed = time.time() - float(state.get("score_a_updated_at", 0))
    if elapsed < interval:
        return {"status": "sampled_recently"}
    max_frames = 2 if at_risk else 1
    try:
        latest, embeddings = embed_latest_session_chunk(
            storage.SESSIONS_DIR / session_id, max_frames=max_frames)
    except FaceModelUnavailable as exc:
        logger.info("Face-A unavailable locally session=%s: %s", session_id, exc)
        _persist(session_id, {"a_status": "model_unavailable", "score_a": None,
                              "samples_a": 0, "score_a_updated_at": time.time()})
        return {"status": "model_unavailable"}
    except VideoChunkDecodeError as exc:
        logger.warning("Face-A video chunk unavailable session=%s: %s", session_id, exc)
        _persist(session_id, {"a_status": "video_decode_error", "score_a": None,
                              "samples_a": 0, "last_a_chunk": uploaded_path.name,
                              "score_a_updated_at": time.time()})
        return {"status": "video_decode_error"}
    if latest is None:
        return {"status": "no_video"}
    uploaded_path = latest
    score = similarity(embeddings, profile)
    now = time.time()
    rows = [{
        "participant_code": profile_code,
        "actor_code": session["participant_code"],
        "session_id": session_id,
        "condition": session["condition"],
        "kind": "probe",
        "chunk_name": uploaded_path.name,
        "frame_index": frame_index,
        "embedding": embedding.tolist(),
        "created_at": now,
    } for frame_index, embedding in enumerate(embeddings)]
    append_face_a_rows(storage.DATA_DIR, rows)
    _persist(session_id, {
        "a_status": "scored" if score is not None else "no_face",
        "score_a": score,
        "samples_a": len(embeddings),
        "threshold_a": thresholds.get("face_a", {}).get("threshold"),
        "last_a_chunk": uploaded_path.name,
        "last_a_chunk_index": chunk_index,
        "score_a_updated_at": now,
    })
    logger.info("Face-A sampled session=%s chunk=%s frames=%d", session_id, uploaded_path.name, len(embeddings))
    return {"status": "scored" if score is not None else "no_face", "frames": len(embeddings), "score_a": score}
