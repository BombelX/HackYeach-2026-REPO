"""Inference: score a processed session against a person's calm profile.

    /venv/main/bin/python -m training.fusion.infer --session <session_id|dir> --profile <participant_code>

Returns per-window and session-level probabilities:
  p_not_owner  - the person in the session is not the profile owner
  p_pressure   - the owner acts under pressure (only meaningful when p_not_owner is low)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch

from training.fusion.data import Normalizer, Pair, pair_tensors, to_torch
from training.fusion.features import (
    PROCESSED_ROOT, Profile, SessionWindows, _session_dir, build_profile, build_session_windows, load_index,
)
from training.fusion.model import FusionTransformer
from training.fusion.network import attach_network
from training.fusion.train import ART, mask_camera, scale_device_match

MODEL_PATH = ART / "fusion_model.pt"


class FusionPredictor:
    def __init__(self, model_path: str | Path = MODEL_PATH, device: str | None = None):
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        if "network_model" not in ckpt:
            raise ValueError(f"{model_path} was trained without network model; rerun python -m training.fusion.train")
        self.network_model = ckpt["network_model"]
        self.camera_off = ckpt.get("camera_off", False)
        self.device_scale = ckpt.get("device_match_scale", 0.0 if ckpt.get("device_match_off", False) else 1.0)
        self.review_threshold = ckpt.get("review_threshold")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = FusionTransformer(**ckpt["input_dims"], **ckpt["config"])
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.to(self.device).eval()
        self.norm = Normalizer.from_state(ckpt["normalizer"])
        self.index = None

    def _row(self, session: str | Path) -> tuple[Path, dict[str, Any]]:
        path = Path(session)
        if path.is_dir():
            return path, {"session_id": path.name, "participant_code": "?", "condition": "probe"}
        if self.index is None:
            self.index = load_index(PROCESSED_ROOT)
        hit = self.index[self.index["session_id"] == str(session)]
        if hit.empty:
            raise KeyError(f"unknown session {session}")
        row = hit.iloc[0].to_dict()
        return _session_dir(PROCESSED_ROOT, row), row

    def profile_for(self, participant: str) -> Profile:
        """Profile from the first half of the participant's calm_1 session (as in training)."""
        if self.index is None:
            self.index = load_index(PROCESSED_ROOT)
        hit = self.index[(self.index["participant_code"] == participant) & (self.index["condition"] == "calm_1")]
        if hit.empty:
            raise KeyError(f"no calm_1 session for {participant}")
        row = hit.sort_values("session_id").iloc[0].to_dict()
        sw = build_session_windows(_session_dir(PROCESSED_ROOT, row), row)
        prof = build_profile(sw) if sw is not None else None
        if prof is None:
            raise ValueError(f"calm session of {participant} has no usable enrolment windows")
        return prof

    @torch.no_grad()
    def predict(self, session: str | Path, profile: str | Profile,
                net_emb: np.ndarray | None = None, net_mask: np.ndarray | None = None) -> dict[str, Any]:
        """Score network windows with the fold-consistent network model bundled in the checkpoint."""
        prof = profile if isinstance(profile, Profile) else self.profile_for(profile)
        path, row = self._row(session)
        # Score every window: for a calm session this includes its enrolment half, which is fine at
        # inference time but means scoring a profile's own calm session is optimistic.
        row = {**row, "condition": "probe"}
        sw: SessionWindows | None = build_session_windows(path, row)
        if sw is None or not len(sw.starts):
            raise ValueError(f"session {row['session_id']} has no windows")
        if net_emb is not None or net_mask is not None:
            raise ValueError("External network embeddings are not supported by this trained checkpoint")
        attach_network({sw.session_id: sw}, self.network_model)
        key = "__probe__"
        arrays = pair_tensors([Pair(sw.session_id, key, 0, 0, 0, "inference")], {sw.session_id: sw},
                              {key: prof}, self.norm)
        tensors = to_torch(arrays, self.device)
        if self.camera_off:
            tensors = mask_camera(tensors)
        tensors = scale_device_match(tensors, self.device_scale)
        out = self.model(tensors)
        ln, lp = out["nonowner"].float().cpu().numpy(), out["pressure"].float().cpu().numpy()
        sig = lambda v: 1 / (1 + np.exp(-v))  # noqa: E731
        from training.fusion.risk import risk_score

        review_score = float(risk_score(ln.mean(), lp.mean()))
        result = {
            "session_id": sw.session_id, "profile": prof.participant,
            "network_model": "hgb_10s_fold_safe",
            "network_signal": float(sw.net_emb[:, 0].mean()),
            "p_not_owner": float(sig(ln.mean())), "p_pressure": float(sig(lp.mean())),
            "review_score": review_score,
            "windows": [{"start_ms": float(s), "p_not_owner": float(sig(a)), "p_pressure": float(sig(b)),
                         "mask": dict(zip(("keyboard", "mouse", "pulse", "face", "context", "profile"),
                                          map(int, m)))}
                        for s, a, b, m in zip(sw.starts, ln, lp, arrays["mask"])],
        }
        if self.review_threshold is not None:
            result["review_threshold"] = float(self.review_threshold)
            result["review_required"] = bool(review_score >= self.review_threshold)
        return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, help="session_id from data/processed or a session directory")
    ap.add_argument("--profile", required=True, help="participant_code whose calm profile is the reference")
    ap.add_argument("--model", default=str(MODEL_PATH))
    ap.add_argument("--windows", action="store_true", help="also print per-window scores")
    ap.add_argument("--deepfake", action="store_true",
                    help="Score local source video with an optional, unvalidated image model")
    ap.add_argument("--deepfake-video", type=Path,
                    help="Score this video instead of the recorder video for --session; requires --deepfake")
    args = ap.parse_args()
    if args.deepfake_video and not args.deepfake:
        ap.error("--deepfake-video requires --deepfake")
    res = FusionPredictor(args.model).predict(args.session, args.profile)
    if args.deepfake:
        from training.fusion.deepfake import assess_video

        res["deepfake_assessment"] = assess_video(args.session, args.deepfake_video)
    if not args.windows:
        res.pop("windows")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
