#!/usr/bin/env python3
"""Calibrate face-match thresholds using held-out calm sessions and intruder sessions."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

from face.enroll import (  # noqa: E402
    _eligible_sessions, consented_sessions, append_face_a_rows, artifact_dir,
    update_thresholds,
)
from face.features_b import (  # noqa: E402
    extract_session_features, make_unit_profile, cosine_scores, load_face_rows,
)
from face.verify_a import VideoChunkDecodeError, embed_latest_session_chunk  # noqa: E402


def _select_threshold(positive: list[float], negative: list[float]) -> dict:
    pos = np.asarray(positive, dtype=float)
    neg = np.asarray(negative, dtype=float)
    pos, neg = pos[np.isfinite(pos)], neg[np.isfinite(neg)]
    if not len(pos) or not len(neg):
        raise ValueError(f"Need positive and negative calibration scores (got {len(pos)}, {len(neg)})")
    candidates = np.unique(np.concatenate((pos, neg)))
    candidates = (candidates[:-1] + candidates[1:]) / 2 if len(candidates) > 1 else candidates
    best = None
    for threshold in candidates:
        far = float(np.mean(neg >= threshold))
        frr = float(np.mean(pos < threshold))
        key = (abs(far - frr), far + frr)
        if best is None or key < best[0]:
            best = (key, float(threshold), far, frr)
    _, threshold, far, frr = best
    # Probability that a randomly chosen genuine score exceeds a randomly
    # chosen impostor score.  Avoid a sklearn runtime dependency for this
    # small, auditable calibration set; ties get half credit.
    comparisons = pos[:, None] - neg[None, :]
    auc = float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)
    balanced_accuracy = float(1.0 - (far + frr) / 2.0)
    # A threshold with near-chance separation must not turn into a silent
    # account-blocking control merely because a JSON file exists.  It remains
    # useful as study telemetry and can be reviewed in the risk API.
    reliable = bool(
        len(pos) >= 30
        and len(neg) >= 15
        and auc >= 0.70
        and far <= 0.25
        and frr <= 0.25
    )
    return {
        "threshold": threshold, "method": "equal_error_rate",
        "calibration_positive": int(len(pos)), "calibration_negative": int(len(neg)),
        "false_accept_rate": far, "false_reject_rate": frr,
        "roc_auc": auc, "balanced_accuracy": balanced_accuracy,
        "eligible_for_escalation": reliable,
        "warning": "Exploratory calibration on existing participants; validate independently before enforcement.",
    }


def _calibrate_b(data_dir: Path) -> dict:
    eligible = consented_sessions(data_dir)
    profiles_path = artifact_dir(data_dir) / "face_b_profiles.parquet"
    if not profiles_path.is_file():
        raise FileNotFoundError(f"Build calm Face-B enrollment first: {profiles_path}")
    profile_rows = pd.read_parquet(profiles_path).set_index("participant_code")
    names = tuple(profile_rows.iloc[0]["blendshape_names"])
    calm_by_participant: dict[str, list[tuple[str, np.ndarray]]] = {}
    vectors_by_session: dict[str, np.ndarray] = {}
    for session in eligible:
        vectors = extract_session_features(session["session_dir"] / "face.jsonl", names)
        vectors_by_session[session["session_id"]] = vectors
        if session["condition"].startswith("calm") and len(vectors):
            calm_by_participant.setdefault(session["participant_code"], []).append(
                (session["session_id"], make_unit_profile(vectors)))
    positives, negatives = [], []
    for session in eligible:
        participant = (session.get("victim_code") if session["condition"] == "intruder"
                       else session["participant_code"])
        if not participant:
            continue
        vectors = vectors_by_session[session["session_id"]]
        if not len(vectors) or participant not in calm_by_participant:
            continue
        calm_refs = [v for sid, v in calm_by_participant[participant] if sid != session["session_id"]]
        if not calm_refs:
            continue
        profile = make_unit_profile(np.stack(calm_refs))
        score = float(np.median(cosine_scores(vectors, profile)))
        (negatives if session["condition"] == "intruder" else positives).append(score)
    return _select_threshold(positives, negatives)


def _collect_face_a(data_dir: Path) -> None:
    db = data_dir / "participants.sqlite"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT s.id AS session_id, s.condition, s.consents_json,
                      p.code AS participant_code, p.victim_code
               FROM sessions s JOIN participants p ON p.id=s.participant_id
               WHERE p.deleted_at IS NULL ORDER BY s.started_at"""
        ).fetchall()
    embeddings = []
    skipped = 0
    for row in rows:
        item = dict(row)
        consents = json.loads(item.pop("consents_json") or "{}")
        if not consents.get("face_pose") or not consents.get("video"):
            continue
        profile_code = (item.get("victim_code") if item["condition"] == "intruder"
                        else item["participant_code"])
        if not profile_code:
            continue
        try:
            chunk, vectors = embed_latest_session_chunk(
                data_dir / "sessions" / item["session_id"], max_frames=1)
        except VideoChunkDecodeError as exc:
            print(f"Skipping invalid calibration chunk: {exc}", file=sys.stderr)
            skipped += 1
            continue
        if chunk is None:
            continue
        embeddings.extend([{
            "participant_code": profile_code,
            "actor_code": item["participant_code"],
            "session_id": item["session_id"],
            "condition": item["condition"],
            "kind": "calibration_probe",
            "chunk_name": chunk.name,
            "frame_index": i,
            "embedding": vector.tolist(),
            "created_at": float(chunk.stat().st_mtime),
        } for i, vector in enumerate(vectors)])
    append_face_a_rows(data_dir, embeddings)
    print(f"Face-A calibration probes: {len(embeddings)}; invalid chunks skipped: {skipped}")


def _calibrate_a(data_dir: Path, collect_video: bool) -> dict:
    if collect_video:
        _collect_face_a(data_dir)
    path = artifact_dir(data_dir) / "face_a_embeddings.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"Build Face-A calm enrollment first: {path}")
    data = pd.read_parquet(path)
    probes = data[data["kind"] == "calibration_probe"]
    positives, negatives = [], []
    for (participant, session_id, condition), rows in probes.groupby(
            ["participant_code", "session_id", "condition"]):
        profile_rows = data[(data["participant_code"] == participant)
                            & (data["kind"] == "enroll")
                            & (data["session_id"] != session_id)]
        if profile_rows.empty:
            continue
        profile = np.mean(np.asarray(profile_rows["embedding"].tolist(), dtype=np.float32), axis=0)
        norm = float(np.linalg.norm(profile))
        if norm < 1e-8:
            continue
        profile /= norm
        vectors = np.asarray(rows["embedding"].tolist(), dtype=np.float32)
        scores = vectors @ profile
        score = float(np.median(scores))
        (negatives if condition == "intruder" else positives).append(score)
    return _select_threshold(positives, negatives)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--modality", choices=("b", "a"), required=True)
    parser.add_argument("--no-collect-video", action="store_true",
                        help="For Face-A, calibrate only from existing calibration_probe embeddings")
    args = parser.parse_args()
    result = _calibrate_b(args.data_dir) if args.modality == "b" else _calibrate_a(
        args.data_dir, collect_video=not args.no_collect_video)
    update_thresholds(args.data_dir, {f"face_{args.modality}": result})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
