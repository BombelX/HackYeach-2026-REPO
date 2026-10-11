# LEGACY / DO NOT USE. Kept for reference only.
# The features below include survey stress/hurry (filled in AFTER the session) and the old
# context_vector encodes condition/group, so the xgboost pickles score labels, not behaviour.
# Replacement: training/inference_xgb_suspicious.py -> training/fusion/infer.py
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODEL_PATH = Path("/workspace/hackaton/HackYeach-2026-REPO/training/artifacts/xgboost/xgb_suspicious_model.pkl")


def _as_1d_float_array(value: Any, length: int = 128) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float32)
    arr = np.asarray(arr, dtype=np.float32).reshape(-1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if arr.size < length:
        arr = np.pad(arr, (0, length - arr.size), constant_values=0.0)
    return arr[:length].astype(np.float32)


def _feature_vector_from_record(record: dict[str, Any] | Any) -> np.ndarray:
    """Build the same feature vector used during XGBoost training.

    Training used the following concatenation for each session:
    - keyboard_vector
    - mouse_vector
    - pulse_vector
    - face_vector
    - context_vector
    - profile_vector
    - token_mask
    - [stress, hurry]
    """
    if hasattr(record, "keyboard_vector"):
        rec = record
        keyboard = np.asarray(rec.keyboard_vector, dtype=np.float32).reshape(-1)
        mouse = np.asarray(rec.mouse_vector, dtype=np.float32).reshape(-1)
        pulse = np.asarray(rec.pulse_vector, dtype=np.float32).reshape(-1)
        face = np.asarray(rec.face_vector, dtype=np.float32).reshape(-1)
        context = np.asarray(rec.context_vector, dtype=np.float32).reshape(-1)
        profile = np.asarray(rec.profile_vector, dtype=np.float32).reshape(-1)
        token_mask = np.asarray(rec.token_mask, dtype=np.float32).reshape(-1)
        stress = float(getattr(rec, "stress", 0.0))
        hurry = float(getattr(rec, "hurry", 0.0))
    else:
        rec = dict(record)
        keyboard = _as_1d_float_array(rec.get("keyboard_vector", np.zeros(128, dtype=np.float32)), 128)
        mouse = _as_1d_float_array(rec.get("mouse_vector", np.zeros(128, dtype=np.float32)), 128)
        pulse = _as_1d_float_array(rec.get("pulse_vector", np.zeros(128, dtype=np.float32)), 128)
        face = _as_1d_float_array(rec.get("face_vector", np.zeros(128, dtype=np.float32)), 128)
        context = _as_1d_float_array(rec.get("context_vector", np.zeros(128, dtype=np.float32)), 128)
        profile = _as_1d_float_array(rec.get("profile_vector", np.zeros(128, dtype=np.float32)), 128)
        token_mask = _as_1d_float_array(rec.get("token_mask", np.zeros(6, dtype=np.float32)), 6)
        stress = float(rec.get("stress", 0.0))
        hurry = float(rec.get("hurry", 0.0))

    keyboard = _as_1d_float_array(keyboard, 128)
    mouse = _as_1d_float_array(mouse, 128)
    pulse = _as_1d_float_array(pulse, 128)
    face = _as_1d_float_array(face, 128)
    context = _as_1d_float_array(context, 128)
    profile = _as_1d_float_array(profile, 128)
    token_mask = _as_1d_float_array(token_mask, 6)

    tokens = np.concatenate([
        keyboard,
        mouse,
        pulse,
        face,
        context,
        profile,
    ], axis=0).astype(np.float32)
    extras = np.asarray([stress, hurry], dtype=np.float32)
    full = np.concatenate([tokens, token_mask, extras], axis=0).astype(np.float32)
    return full.reshape(1, -1)


def load_model(model_path: str | Path = MODEL_PATH):
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    return model


def predict_suspicious(record: dict[str, Any] | Any, model_path: str | Path = MODEL_PATH, threshold: float = 0.5):
    model = load_model(model_path)
    x = _feature_vector_from_record(record)
    proba = model.predict_proba(x)[0, 1]
    pred = int(proba >= threshold)
    return {
        "prediction": pred,
        "probability": float(proba),
        "feature_shape": list(x.shape),
        "model_path": str(Path(model_path)),
    }


def _example_record():
    from training.fusion_session_model import build_session_records

    records = build_session_records()
    if not records:
        raise RuntimeError("No processed session records were found.")
    return records[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inference for the saved XGBoost suspicious model.")
    parser.add_argument("--record-json", type=str, default=None, help="Optional JSON string with a session record dictionary.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Decision threshold for the positive class.")
    args = parser.parse_args()

    if args.record_json:
        record = json.loads(args.record_json)
    else:
        record = _example_record()

    result = predict_suspicious(record, threshold=args.threshold)
    print(json.dumps(result, indent=2))
