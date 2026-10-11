import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import storage
from server.face import worker
from server.face.enroll import artifact_dir
from server.face.features_b import LANDMARK_IDS, face_feature
from server.face.verify_a import FaceModelUnavailable


@pytest.fixture
def face_store(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "DB_PATH", data_dir / "participants.sqlite")
    monkeypatch.setattr(storage, "SESSIONS_DIR", data_dir / "sessions")
    storage.init_db()
    conn = storage.connect()
    conn.execute(
        """INSERT INTO participants(code, created_at, identity_json, victim_code, condition_order)
           VALUES ('P-OWNER', 1, '{}', NULL, '[]')"""
    )
    conn.commit()
    conn.close()
    return data_dir


def add_session(condition="calm_1", consents=None):
    conn = storage.connect()
    conn.execute(
        """INSERT INTO sessions(id, participant_id, condition, order_index, started_at, consents_json)
           VALUES ('session-1', 1, ?, 0, 1, ?)""",
        (condition, json.dumps(consents or {"face_pose": True, "video": True})),
    )
    conn.commit()
    conn.close()


def sample_face_row():
    return {
        "face_key": [
            {"i": i, "x": 0.3 + i * 0.001, "y": 0.35 + i * 0.0005, "z": i * 0.0001}
            for i in LANDMARK_IDS
        ],
        "blendshapes": {"jawOpen": 0.1, "eyeBlinkLeft": 0.02},
    }


def test_calm_enrollment_face_b_scores_high(face_store):
    add_session()
    row = sample_face_row()
    names = tuple(sorted(row["blendshapes"]))
    embedding = face_feature(row, names)
    assert embedding is not None
    artifact = artifact_dir(face_store) / "face_b_profiles.parquet"
    pd.DataFrame([{
        "participant_code": "P-OWNER", "embedding": embedding.tolist(),
        "blendshape_names": list(names), "n_frames": 2, "n_sessions": 1,
        "session_ids": ["enrollment"], "updated_at": 1,
    }]).to_parquet(artifact, index=False)

    result = worker.update_face_b("session-1", [row])
    assert result["score_b"] == pytest.approx(1.0, abs=1e-5)
    assert result["b_status"] == "scored"


def test_intruder_face_a_scores_low(face_store, monkeypatch):
    conn = storage.connect()
    conn.execute(
        """INSERT INTO participants(code, created_at, identity_json, victim_code, condition_order)
           VALUES ('P-ACTOR', 1, '{}', 'P-OWNER', '[]')"""
    )
    conn.execute(
        """INSERT INTO sessions(id, participant_id, condition, order_index, started_at, consents_json)
           VALUES ('session-1', 2, 'intruder', 0, 1, ?)""",
        (json.dumps({"face_pose": True, "video": True}),),
    )
    conn.commit()
    conn.close()
    embeddings_path = artifact_dir(face_store) / "face_a_embeddings.parquet"
    reference = np.zeros(512, dtype=np.float32)
    reference[0] = 1
    pd.DataFrame([{
        "participant_code": "P-OWNER", "session_id": "calm",
        "condition": "calm_1", "kind": "enroll", "chunk_name": "0000.webm",
        "frame_index": 0, "embedding": reference.tolist(), "created_at": 1,
    }]).to_parquet(embeddings_path, index=False)
    chunk = storage.session_dir("session-1") / "video" / "0001.webm"
    chunk.write_bytes(b"test")
    impostor = np.zeros(512, dtype=np.float32)
    impostor[1] = 1
    # The worker samples the newest chunk through the session-aware helper so
    # non-standalone MediaRecorder chunks can fall back to the joined stream.
    monkeypatch.setattr(
        worker,
        "embed_latest_session_chunk",
        lambda *_args, **_kwargs: (chunk, [impostor]),
    )

    result = worker.process_video_chunk("session-1", chunk, 1)
    assert result["score_a"] == pytest.approx(0.0)
    assert result["status"] == "scored"


def test_missing_face_consent_returns_no_consent(face_store):
    add_session(consents={"face_pose": False, "video": True})
    result = worker.update_face_b("session-1", [sample_face_row()])
    risk = worker.risk_for_session("session-1")
    assert result["b_status"] == "no_consent"
    assert risk["status"] == "no_consent"
    assert risk["score_b"] is None
    assert risk["score_a"] is None
    assert risk["escalation"] is False


def test_face_a_missing_local_model_degrades_without_failing_upload(face_store, monkeypatch):
    add_session()
    artifact = artifact_dir(face_store) / "face_a_embeddings.parquet"
    reference = np.zeros(512, dtype=np.float32)
    reference[0] = 1
    pd.DataFrame([{
        "participant_code": "P-OWNER", "session_id": "calm", "condition": "calm_1",
        "kind": "enroll", "chunk_name": "0000.webm", "frame_index": 0,
        "embedding": reference.tolist(), "created_at": 1,
    }]).to_parquet(artifact, index=False)
    chunk = storage.session_dir("session-1") / "video" / "0000.webm"
    chunk.write_bytes(b"test")
    monkeypatch.setattr(
        worker, "embed_latest_session_chunk",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FaceModelUnavailable("not provisioned")),
    )

    assert worker.process_video_chunk("session-1", chunk, 0)["status"] == "model_unavailable"
    assert worker.risk_for_session("session-1")["score_a"] is None


def test_weak_calibration_cannot_trigger_automatic_escalation(face_store):
    add_session()
    storage.merge_json("session-1", "face_verification.json", {
        "b_status": "scored", "score_b": 0.1, "samples_b": 1,
    })
    thresholds = artifact_dir(face_store) / "face_thresholds.json"
    thresholds.write_text(json.dumps({"face_b": {"threshold": 0.9, "eligible_for_escalation": False}}))

    risk = worker.risk_for_session("session-1")
    assert risk["calibration_b_reliable"] is False
    assert risk["status"] == "exploratory_calibration"
    assert risk["escalation"] is False


def test_reliable_calibration_escalates_on_low_score(face_store):
    add_session()
    storage.merge_json("session-1", "face_verification.json", {
        "b_status": "scored", "score_b": 0.1, "samples_b": 1,
    })
    thresholds = artifact_dir(face_store) / "face_thresholds.json"
    thresholds.write_text(json.dumps({"face_b": {"threshold": 0.9, "eligible_for_escalation": True}}))

    risk = worker.risk_for_session("session-1")
    assert risk["calibration_b_reliable"] is True
    assert risk["escalation_reasons"] == ["face_b_below_threshold"]
