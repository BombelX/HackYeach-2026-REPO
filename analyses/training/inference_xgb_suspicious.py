#!/usr/bin/env python3
"""Suspicious-session inference (replaces the old XGBoost script).

The previous version fed ``[stress, hurry]`` from the post-session survey plus a context vector that
encoded ``condition``/``group`` into XGBoost, so its AUC came from the labels themselves (see
``inference_xgb_suspicious_legacy.py`` and ``training/fusion/README.md``). This entry point keeps the
same name but scores a session with the leak-free fusion transformer against a calm profile.

    /venv/main/bin/python training/inference_xgb_suspicious.py --session <session_id> --profile <participant_code>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from training.fusion.features import Profile  # noqa: E402
from training.fusion.infer import MODEL_PATH, FusionPredictor  # noqa: E402

_PREDICTORS: dict[str, FusionPredictor] = {}


def load_model(model_path: str | Path = MODEL_PATH) -> FusionPredictor:
    key = str(model_path)
    if key not in _PREDICTORS:
        _PREDICTORS[key] = FusionPredictor(model_path)
    return _PREDICTORS[key]


def predict_suspicious(session: str | Path, profile: str | Profile, model_path: str | Path = MODEL_PATH,
                       threshold: float | None = None, deepfake: bool = False,
                       deepfake_video: Path | None = None) -> dict[str, Any]:
    """Human-review flag; not a calibrated probability of fraud."""
    if deepfake_video is not None and not deepfake:
        raise ValueError("deepfake_video requires deepfake=True")
    res = load_model(model_path).predict(session, profile)
    if threshold is None:
        if "review_threshold" not in res:
            raise ValueError("Model has no review threshold; retrain with training.fusion.train")
        threshold = res["review_threshold"]
    if not 0 <= threshold <= 1:
        raise ValueError("Review threshold must be between 0 and 1")
    result = {
        "session_id": res["session_id"], "profile": res["profile"],
        "prediction": int(res["review_score"] >= threshold),
        "review_required": bool(res["review_score"] >= threshold),
        "review_score": res["review_score"], "review_threshold": float(threshold),
        "p_not_owner": res["p_not_owner"], "p_pressure": res["p_pressure"],
        "model_path": str(Path(model_path)),
    }
    if deepfake:
        from training.fusion.deepfake import assess_video

        result["deepfake_assessment"] = assess_video(session, deepfake_video)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--session", required=True, help="session_id from data/processed or a session directory")
    parser.add_argument("--profile", required=True, help="participant_code of the account owner (calm profile)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override saved review threshold (changes false alarm/miss trade-off)")
    parser.add_argument("--model", default=str(MODEL_PATH))
    parser.add_argument("--deepfake", action="store_true",
                        help="Optional, unvalidated local video assessment; does not change the review flag")
    parser.add_argument("--deepfake-video", type=Path, help="Video to score instead of local session chunks")
    args = parser.parse_args()
    if args.deepfake_video and not args.deepfake:
        parser.error("--deepfake-video requires --deepfake")
    print(json.dumps(predict_suspicious(args.session, args.profile, args.model, args.threshold,
                                        args.deepfake, args.deepfake_video), indent=2))
