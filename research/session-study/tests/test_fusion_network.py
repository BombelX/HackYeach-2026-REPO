import numpy as np
import pytest

from training.fusion.features import CONTEXT_WINDOW_FEATURES, NETWORK_WINDOW_FEATURES, SessionWindows
from training.fusion.network import attach_crossfit_network, network_features


def _session(user: str, condition: str, value: float) -> SessionWindows:
    n = 3
    ctx = np.zeros((n, len(CONTEXT_WINDOW_FEATURES)), dtype=np.float32)
    ctx[:, -len(NETWORK_WINDOW_FEATURES):] = value
    return SessionWindows(
        session_id=f"{user}-{condition}", participant=user, condition=condition, victim=None,
        starts=np.arange(n, dtype=np.float32) * 5000,
        kb=np.zeros((n, 128), dtype=np.float32), kb_mask=np.zeros(n, dtype=np.float32),
        mouse=np.zeros((n, 1), dtype=np.float32), mouse_mask=np.zeros(n, dtype=np.float32),
        pulse=np.zeros((n, 1), dtype=np.float32), pulse_mask=np.zeros(n, dtype=np.float32),
        face=np.zeros((n, 1), dtype=np.float32), face_mask=np.zeros(n, dtype=np.float32),
        ctx=ctx,
    )


def test_network_crossfit_does_not_train_on_test_person():
    sessions = {}
    for i in range(12):
        for label, c in enumerate(("calm_1", "scam")):
            sw = _session(f"P{i}", c, float(label * 2 + i / 10))
            sessions[sw.session_id] = sw
    train = {f"P{i}" for i in range(11)}
    model = attach_crossfit_network(sessions, train)
    hold = sessions["P11-scam"]
    before = hold.net_emb.copy()
    # Altering the label of an unseen session must not alter the fitted network model.
    hold.condition = "dictation"
    model2 = attach_crossfit_network(sessions, train)
    np.testing.assert_allclose(model.predict_proba(network_features(hold)),
                               model2.predict_proba(network_features(hold)))
    np.testing.assert_allclose(before, hold.net_emb)
    assert all(sw.net_mask.all() and sw.net_emb.shape == (3, 64) for sw in sessions.values())
    assert any(np.any(sw.net_emb[:, 0] != 0) for sw in sessions.values())


def test_network_features_reject_nonfinite():
    sw = _session("P", "calm_1", 1)
    sw.ctx[0, -1] = np.nan
    with pytest.raises(ValueError, match="Invalid network features"):
        network_features(sw)
