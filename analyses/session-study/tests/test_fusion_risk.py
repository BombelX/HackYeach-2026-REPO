from unittest.mock import patch

import numpy as np
import pytest

from training.fusion.data import Pair
from training.fusion.risk import alarm_counts, risk_score, select_threshold
from training.inference_xgb_suspicious import predict_suspicious


def _pairs():
    return [
        Pair("calm", "A", 0, 0, 1, "owner_calm_1"),
        Pair("scam1", "A", 0, 1, 1, "owner_scam"),
        Pair("scam2", "B", 0, 1, 1, "owner_scam"),
        Pair("impostor", "A", 1, 0, 0, "impostor_calm_1"),
    ]


def test_recall_threshold_includes_all_scarce_scams():
    scores = np.array([0.05, 0.15, 0.9, 0.7])
    threshold = select_threshold(_pairs(), scores)
    assert threshold == 0.15
    counts = alarm_counts(_pairs(), scores, threshold)
    assert counts["scam_owner"]["missed"] == 0
    assert counts["normal_owner"]["flagged"] == 0
    assert select_threshold(_pairs(), scores, 0.5) == 0.7


def test_missing_category_and_invalid_scores_fail_explicitly():
    with pytest.raises(ValueError, match="both scam-owner"):
        select_threshold(_pairs()[:1], [0.2])
    with pytest.raises(ValueError, match="finite score"):
        select_threshold(_pairs(), [0, 0.1, np.nan, 0.4])


def test_combined_score_and_default_saved_threshold():
    assert float(risk_score(0, 0)) == 0.75
    with patch("training.inference_xgb_suspicious.load_model") as load:
        load.return_value.predict.return_value = {
            "session_id": "s", "profile": "p", "review_score": 0.3,
            "review_threshold": 0.2, "p_not_owner": 0.1, "p_pressure": 0.2,
        }
        out = predict_suspicious("s", "p")
        assert out["review_required"] is True and out["review_threshold"] == 0.2
        assert "probability" not in out
        assert predict_suspicious("s", "p", threshold=0.5)["review_required"] is False
        with pytest.raises(ValueError, match="between 0 and 1"):
            predict_suspicious("s", "p", threshold=-0.1)
        load.return_value.predict.return_value.pop("review_threshold")
        with pytest.raises(ValueError, match="no review threshold"):
            predict_suspicious("s", "p")
