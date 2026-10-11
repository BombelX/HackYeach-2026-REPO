from unittest.mock import patch

import numpy as np
import torch

from training.fusion.data import Pair
from training.fusion.data import INPUT_DIMS
from training.fusion.features import CONTEXT_PAIR_FEATURES
from training.fusion.model import FusionTransformer, count_parameters
from training.fusion.train import VARIANTS, mask_camera, mask_device_match, scale_device_match, validation_loss


def test_validation_loss_responds_to_confidence_at_constant_auc():
    pairs = [
        Pair("a", "p", 0, 0, 1, "owner_calm"),
        Pair("b", "p", 0, 1, 1, "owner_scam"),
        Pair("c", "p", 1, 0, 0, "impostor"),
    ]
    # AUC of both outputs is unchanged, but confidence differs.
    with patch("training.fusion.train.pair_scores", return_value=(
        np.array([-0.2, -0.2, 0.2]), np.array([-0.2, 0.2, 0.0]))):
        weak = validation_loss(None, {}, pairs)
    with patch("training.fusion.train.pair_scores", return_value=(
        np.array([-2.0, -2.0, 2.0]), np.array([-2.0, 2.0, 0.0]))):
        strong = validation_loss(None, {}, pairs)
    assert strong < weak


def test_all_variants_fit_parameter_budget():
    counts = {name: count_parameters(FusionTransformer(**INPUT_DIMS, **config))
              for name, (config, _) in VARIANTS.items()}
    assert counts["compact"] < counts["baseline"] < counts["wider"] < 1_000_000


def test_camera_mask_removes_profile_as_well_as_probe():
    n = 3
    stats = np.ones((n, INPUT_DIMS["profile_stats_dim"]), dtype=np.float32)
    batch = {
        "mask": torch.ones(n, 6),
        "profile_stats": torch.from_numpy(stats),
    }
    camera_free = mask_camera(batch)
    start = INPUT_DIMS["mouse_dim"]
    end = start + INPUT_DIMS["pulse_dim"] + INPUT_DIMS["face_dim"]
    assert camera_free["mask"][:, 2:4].count_nonzero() == 0
    assert camera_free["profile_stats"][:, start:end].count_nonzero() == 0
    assert camera_free["profile_stats"][:, -3:-1].count_nonzero() == 0
    assert camera_free["profile_stats"][:, :start].all()
    assert camera_free["profile_stats"][:, -1].all()
    assert batch["profile_stats"].all()  # original tensors are untouched


def test_device_match_mask_removes_only_pairwise_device_features():
    ctx = torch.arange(INPUT_DIMS["ctx_dim"], dtype=torch.float32)[None].repeat(2, 1)
    original = {"ctx": ctx}
    masked = mask_device_match(original)
    match_start = INPUT_DIMS["ctx_dim"] - len(CONTEXT_PAIR_FEATURES)
    torch.testing.assert_close(masked["ctx"][:, :match_start], ctx[:, :match_start])
    assert not masked["ctx"][:, match_start:].any()
    assert original["ctx"][:, match_start:].any()


def test_device_match_scale_and_dropout_preserve_other_context_and_source():
    ctx = torch.ones((64, INPUT_DIMS["ctx_dim"]))
    source = {"ctx": ctx}
    start = INPUT_DIMS["ctx_dim"] - len(CONTEXT_PAIR_FEATURES)
    scaled = scale_device_match(source, 0.25)
    torch.testing.assert_close(scaled["ctx"][:, :start], ctx[:, :start])
    torch.testing.assert_close(scaled["ctx"][:, start:], ctx[:, start:] * 0.25)
    torch.manual_seed(7)
    dropped = scale_device_match(source, 0.25, dropout=0.5)
    assert (dropped["ctx"][:, start:].sum(1) == 0).any()
    assert (dropped["ctx"][:, start:].sum(1) > 0).any()
    torch.testing.assert_close(dropped["ctx"][:, :start], ctx[:, :start])
    assert ctx.all()
