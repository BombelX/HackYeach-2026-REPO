"""Fold-local network model; no model trained on held-out people enters fusion CV."""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from training.fusion.features import NETWORK_WINDOW_FEATURES, SessionWindows

NETWORK_CONFIG = dict(max_depth=3, learning_rate=0.06, max_iter=250,
                      min_samples_leaf=8, l2_regularization=1.0, random_state=42)


def network_features(sw: SessionWindows) -> np.ndarray:
    x = sw.ctx[:, -len(NETWORK_WINDOW_FEATURES):]
    if x.shape != (len(sw.starts), len(NETWORK_WINDOW_FEATURES)) or not np.isfinite(x).all():
        raise ValueError(f"Invalid network features for {sw.session_id}")
    return x


def fit_network(sessions: dict[str, SessionWindows], train_people: set[str]) -> HistGradientBoostingClassifier:
    """Train on window features, with each session assigned equal total weight per class."""
    rows, labels, weights = [], [], []
    for sw in sessions.values():
        if sw.participant not in train_people:
            continue
        x = network_features(sw)
        if not len(x):
            continue
        # The existing network notebook defined pressure as scam OR intruder.
        label = int(sw.condition in ("scam", "intruder"))
        rows.append(x)
        labels.extend([label] * len(x))
        weights.extend([1 / len(x)] * len(x))
    if not rows:
        raise ValueError("No network windows for training")
    y = np.asarray(labels)
    if len(np.unique(y)) != 2:
        raise ValueError("Network training requires both benign and scam/intruder sessions")
    w = np.asarray(weights)
    for label in (0, 1):
        selected = y == label
        w[selected] *= 0.5 / w[selected].sum()
    model = HistGradientBoostingClassifier(**NETWORK_CONFIG)
    model.fit(np.concatenate(rows), y, sample_weight=w)
    return model


def attach_network(sessions: dict[str, SessionWindows], model: HistGradientBoostingClassifier) -> None:
    """Write network scores to the existing 64D context slot; never read true owner at inference."""
    for sw in sessions.values():
        x = network_features(sw)
        emb = np.zeros((len(x), 64), dtype=np.float32)
        emb[:, 0] = model.predict_proba(x)[:, 1].astype(np.float32)
        sw.net_emb = emb
        sw.net_mask = np.ones(len(x), dtype=np.float32)


def attach_crossfit_network(sessions: dict[str, SessionWindows], train_people: set[str],
                            seed: int = 42) -> HistGradientBoostingClassifier:
    """Training people receive out-of-fold scores; validation/test use train-only model.

    In-sample supervised network probabilities would reveal the pressure label to the
    fusion model during its training, while validation probabilities would not.
    """
    people = np.array(sorted(train_people))
    if len(people) < 4:
        raise ValueError("Network crossfit needs at least four training people")
    rng = np.random.default_rng(seed)
    rng.shuffle(people)
    full = fit_network(sessions, train_people)
    attach_network(sessions, full)
    for held in np.array_split(people, min(5, len(people))):
        inner = fit_network(sessions, train_people - set(held))
        subset = {sid: sw for sid, sw in sessions.items() if sw.participant in held}
        attach_network(subset, inner)
    return full
