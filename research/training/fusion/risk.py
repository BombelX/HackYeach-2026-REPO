"""Review-alarm policy; scores are uncalibrated and are not fraud probabilities."""
from __future__ import annotations

import numpy as np
from scipy.special import expit

from training.fusion.data import Pair

TARGET_RECALL = 0.95


def risk_score(nonowner_logit: np.ndarray, pressure_logit: np.ndarray) -> np.ndarray:
    nonowner = expit(np.asarray(nonowner_logit))
    pressure = expit(np.asarray(pressure_logit))
    return nonowner + (1 - nonowner) * pressure


def select_threshold(pairs: list[Pair], scores: np.ndarray, target: float = TARGET_RECALL) -> float:
    """Highest threshold with target recall for *each* positive category on validation.

    With 1-3 validation scams this generally requires detecting every one; that
    empirical target does not guarantee recall on new people.
    """
    if not 0 < target <= 1:
        raise ValueError("target recall must be in (0, 1]")
    scores = np.asarray(scores, dtype=float)
    if len(pairs) != len(scores) or not np.isfinite(scores).all():
        raise ValueError("One finite score per validation pair is required")
    cutoffs = []
    for select in (
        np.array([p.kind == "owner_scam" for p in pairs]),
        np.array([p.nonowner == 1 for p in pairs]),
    ):
        positives = np.sort(scores[select])
        if len(positives) == 0:
            raise ValueError("Validation needs both scam-owner and impostor pairs")
        # With >= comparison, index floor(n * (1-target)) yields at least target recall.
        cutoff = positives[len(positives) - int(np.ceil(target * len(positives)))]
        cutoffs.append(cutoff)
    return float(min(cutoffs))


def alarm_counts(pairs: list[Pair], scores: np.ndarray, threshold: float) -> dict[str, dict[str, int | float | None]]:
    if len(pairs) != len(scores):
        raise ValueError("One score per pair is required")
    alarm = np.asarray(scores) >= threshold
    categories = {
        "scam_owner": np.array([p.kind == "owner_scam" for p in pairs]),
        "impostor": np.array([p.nonowner == 1 for p in pairs]),
        "natural_intruder": np.array([p.kind == "intruder_victim" for p in pairs]),
        "normal_owner": np.array([p.pressure_valid == 1 and p.pressure == 0 for p in pairs]),
    }
    return {
        name: {"total": int(mask.sum()), "flagged": int(alarm[mask].sum()),
               "missed": int((~alarm[mask]).sum()),
               "rate": float(alarm[mask].mean()) if mask.any() else None}
        for name, mask in categories.items()
    }
