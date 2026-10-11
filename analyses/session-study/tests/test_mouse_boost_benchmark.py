import numpy as np
import pandas as pd
import pytest

from training.mouse_boost_benchmark import (
    metrics, pair_data, person_folds, scale_from_training, score_mouse,
)


def _frame():
    return pd.DataFrame([
        {"user_id": 1, "task_no": 1, "session_id": 11, "speed": 1.0},
        {"user_id": 1, "task_no": 2, "session_id": 12, "speed": 1.1},
        {"user_id": 2, "task_no": 1, "session_id": 21, "speed": 5.0},
        {"user_id": 2, "task_no": 2, "session_id": 22, "speed": 5.1},
    ])


def test_impostor_probe_is_not_standardized_against_true_owner():
    frame = _frame()
    center, scale = scale_from_training(frame, ["speed"], {1, 2})
    x, y, ids = pair_data(frame, ["speed"], {1, 2}, center, scale, seed=3, negatives=1)
    probe = x[ids == 12, 0]
    labels = y[ids == 12]
    assert probe[labels == 1][0] < probe[labels == 0][0]
    assert probe[labels == 0][0] > 0
    assert metrics(y, -x.sum(1))["auc"] == 1.0


def test_scaler_does_not_see_test_user():
    frame = _frame()
    center, scale = scale_from_training(frame, ["speed"], {1})
    changed = frame.copy()
    changed.loc[changed.user_id == 2, "speed"] = 1_000_000
    new_center, new_scale = scale_from_training(changed, ["speed"], {1})
    np.testing.assert_array_equal(center, new_center)
    np.testing.assert_array_equal(scale, new_scale)


def test_split_users_are_disjoint():
    frame = pd.concat([_frame().assign(user_id=lambda f: f.user_id + i * 2,
                                       session_id=lambda f: f.session_id + i * 100)
                       for i in range(5)])
    test_users = []
    for train, val, test in person_folds(frame, folds=5, seed=42):
        assert not train & val
        assert not train & test
        assert not val & test
        assert len(test & set(frame.loc[frame.task_no == 1, "user_id"])) >= 2
        test_users.extend(test)
    assert sorted(test_users) == sorted(frame.user_id.unique())


def test_inference_rejects_missing_enrollment(tmp_path):
    with pytest.raises(ValueError, match="enrollment"):
        score_mouse({"speed": 1.0}, pd.DataFrame(), tmp_path)
    with pytest.raises(ValueError, match="task-1"):
        score_mouse({"speed": 1.0}, pd.DataFrame([{"task_no": 2}]), tmp_path)
