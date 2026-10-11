from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import torch

from training.fusion.deepfake import score_frames, score_session_video
from training.inference_xgb_suspicious import predict_suspicious


def test_image_model_score_uses_deepfake_label_not_class_order():
    processor = Mock(return_value={"pixel_values": torch.zeros(2, 3, 224, 224)})
    model = Mock()
    model.config.id2label = {0: "Deepfake", 1: "Realism"}
    model.return_value = SimpleNamespace(logits=torch.tensor([[2.0, 0.0], [0.0, 2.0]]))
    result = score_frames([object(), object()], processor, model, "cpu")
    assert result["status"] == "scored_unvalidated"
    assert result["frames_scored"] == 2
    assert result["fake_frame_score_max"] == pytest.approx(0.880797, abs=1e-5)
    assert result["fake_frame_score_median"] == pytest.approx(0.5)


def test_unknown_model_labels_are_an_error():
    model = SimpleNamespace(config=SimpleNamespace(id2label={0: "Real", 1: "Fake"}))
    with pytest.raises(ValueError, match="Unsupported deepfake model labels"):
        score_frames([object()], Mock(), model, "cpu")


def test_missing_video_is_unavailable_not_authentic(tmp_path: Path):
    result = score_session_video("missing", source_root=tmp_path)
    assert result == {"status": "unavailable", "reason": "no_source_video", "frames_scored": 0}


def test_legacy_cli_keeps_review_decision_independent_of_video_assessment():
    with pytest.raises(ValueError, match="requires deepfake"):
        predict_suspicious("s", "p", deepfake_video=Path("video.webm"))
    with pytest.MonkeyPatch.context() as patch:
        predictor = Mock()
        predictor.predict.return_value = {
            "session_id": "s", "profile": "p", "review_score": 0.2,
            "review_threshold": 0.5, "p_not_owner": 0.1, "p_pressure": 0.1,
        }
        patch.setattr("training.inference_xgb_suspicious.load_model", lambda _: predictor)
        patch.setattr("training.fusion.deepfake.assess_video", lambda *args: {"status": "scored_unvalidated"})
        result = predict_suspicious("s", "p", deepfake=True)
    assert result["review_required"] is False
    assert result["deepfake_assessment"]["status"] == "scored_unvalidated"
