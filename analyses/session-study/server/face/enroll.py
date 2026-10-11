from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .features_b import extract_session_features, make_unit_profile
from .verify_a import VideoChunkDecodeError, embed_latest_session_chunk

_write_lock = threading.Lock()
logger = logging.getLogger(__name__)


def artifact_dir(data_dir: Path) -> Path:
    path = data_dir / "processed" / "models" / "face"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        frame.to_parquet(tmp, index=False)
        tmp.chmod(0o600)
        tmp.replace(path)
        path.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


def consented_sessions(data_dir: Path) -> list[dict]:
    db_path = data_dir / "participants.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError(f"Collector database not found: {db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT s.id AS session_id, s.condition, s.consents_json,
                      p.code AS participant_code, p.victim_code
               FROM sessions s JOIN participants p ON p.id=s.participant_id
               WHERE p.deleted_at IS NULL ORDER BY p.code, s.started_at"""
        ).fetchall()
    eligible = []
    for row in rows:
        item = dict(row)
        item["consents"] = json.loads(item.pop("consents_json") or "{}")
        if item["consents"].get("face_pose"):
            item["session_dir"] = data_dir / "sessions" / item["session_id"]
            eligible.append(item)
    return eligible


def _eligible_sessions(data_dir: Path) -> list[dict]:
    return [session for session in consented_sessions(data_dir)
            if session["condition"].startswith("calm")]


def build_face_b_profiles(data_dir: Path) -> pd.DataFrame:
    sessions = _eligible_sessions(data_dir)
    names = sorted({name for session in sessions
                    for row in _read_jsonl(session["session_dir"] / "face.jsonl")
                    for name in (row.get("blendshapes") or {})})
    if not names:
        raise ValueError("No consented calm face/blendshape rows found")
    names_tuple = tuple(names)
    by_participant: dict[str, list[tuple[str, np.ndarray, int]]] = {}
    for session in sessions:
        vectors = extract_session_features(session["session_dir"] / "face.jsonl", names_tuple)
        if len(vectors):
            by_participant.setdefault(session["participant_code"], []).append(
                (session["session_id"], make_unit_profile(vectors), len(vectors)))
    rows = []
    for participant, participant_sessions in sorted(by_participant.items()):
        session_means = np.stack([row[1] for row in participant_sessions])
        profile = make_unit_profile(session_means)
        rows.append({
            "participant_code": participant,
            "embedding": profile.tolist(),
            "blendshape_names": names,
            "n_frames": sum(row[2] for row in participant_sessions),
            "n_sessions": len(participant_sessions),
            "session_ids": [row[0] for row in participant_sessions],
            "updated_at": time.time(),
        })
    if not rows:
        raise ValueError("No usable calm face profiles could be built")
    target = artifact_dir(data_dir) / "face_b_profiles.parquet"
    with _write_lock:
        _write_parquet_atomic(pd.DataFrame(rows), target)
    return pd.DataFrame(rows)


def _read_jsonl(path: Path) -> list[dict]:
    from .features_b import load_face_rows

    return load_face_rows(path)


def build_face_a_enrollments(data_dir: Path) -> pd.DataFrame:
    rows = []
    for session in _eligible_sessions(data_dir):
        if not session["consents"].get("video"):
            continue
        try:
            chunk, embeddings = embed_latest_session_chunk(session["session_dir"], max_frames=2)
        except VideoChunkDecodeError as exc:
            logger.warning("Skipping unusable calm enrollment chunk: %s", exc)
            continue
        if chunk is None:
            continue
        for index, embedding in enumerate(embeddings):
            rows.append({
                "participant_code": session["participant_code"],
                "session_id": session["session_id"],
                "condition": session["condition"],
                "kind": "enroll",
                "chunk_name": chunk.name,
                "frame_index": index,
                "embedding": embedding.tolist(),
                "created_at": time.time(),
            })
    if not rows:
        raise ValueError("No usable consented calm video face embeddings found")
    target = artifact_dir(data_dir) / "face_a_embeddings.parquet"
    with _write_lock:
        _write_parquet_atomic(pd.DataFrame(rows), target)
    return pd.DataFrame(rows)


def load_profile_b(data_dir: Path, participant_code: str) -> tuple[np.ndarray, tuple[str, ...]] | None:
    path = artifact_dir(data_dir) / "face_b_profiles.parquet"
    if not path.is_file():
        return None
    frame = pd.read_parquet(path)
    matched = frame[frame["participant_code"] == participant_code]
    if matched.empty:
        return None
    row = matched.iloc[0]
    return np.asarray(row["embedding"], dtype=np.float32), tuple(row["blendshape_names"])


def load_profile_a(data_dir: Path, participant_code: str) -> np.ndarray | None:
    path = artifact_dir(data_dir) / "face_a_embeddings.parquet"
    if not path.is_file():
        return None
    frame = pd.read_parquet(path)
    selected = frame[(frame["participant_code"] == participant_code) & (frame["kind"] == "enroll")]
    if selected.empty:
        return None
    vectors = np.asarray(selected["embedding"].tolist(), dtype=np.float32)
    mean = np.mean(vectors, axis=0)
    norm = float(np.linalg.norm(mean))
    return mean / norm if norm > 1e-8 else None


def append_face_a_rows(data_dir: Path, rows: list[dict]) -> None:
    if not rows:
        return
    target = artifact_dir(data_dir) / "face_a_embeddings.parquet"
    with _write_lock:
        existing = pd.read_parquet(target) if target.is_file() else pd.DataFrame()
        updated = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        dedupe = [c for c in ("session_id", "kind", "chunk_name", "frame_index") if c in updated]
        if dedupe:
            updated = updated.drop_duplicates(subset=dedupe, keep="last")
        _write_parquet_atomic(updated, target)


def update_thresholds(data_dir: Path, values: dict) -> None:
    target = artifact_dir(data_dir) / "face_thresholds.json"
    current = json.loads(target.read_text()) if target.exists() else {}
    current.update(values)
    fd, tmp_name = tempfile.mkstemp(prefix=".face_thresholds.", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(current, indent=2) + "\n")
        tmp.chmod(0o600)
        tmp.replace(target)
        target.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)


def remove_participant_artifacts(data_dir: Path, participant_code: str) -> None:
    directory = artifact_dir(data_dir)
    with _write_lock:
        for name in ("face_b_profiles.parquet", "face_a_embeddings.parquet"):
            path = directory / name
            if not path.is_file():
                continue
            frame = pd.read_parquet(path)
            if "participant_code" not in frame:
                raise ValueError(f"Unexpected face artifact schema: {path}")
            frame = frame[frame["participant_code"] != participant_code]
            if frame.empty:
                path.unlink()
            else:
                _write_parquet_atomic(frame, path)
        # Aggregate thresholds depend on all enrolled participants and must be recalibrated.
        (directory / "face_thresholds.json").unlink(missing_ok=True)
