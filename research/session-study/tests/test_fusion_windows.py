import unittest

import numpy as np
import torch

from training.fusion.data import INPUT_DIMS, Normalizer, build_profiles, make_pairs, pair_tensors, to_torch
from training.fusion.features import (
    CONTEXT_FEATURES, PROCESSED_ROOT, enrol_mask, load_windows, probe_mask,
)
from training.fusion.model import FusionTransformer, count_parameters
from training.fusion.train import CONFIG, person_folds


class FusionModelTest(unittest.TestCase):
    def test_parameter_budget_and_forward(self):
        model = FusionTransformer(**INPUT_DIMS, **CONFIG)
        self.assertLess(count_parameters(model), 1_000_000)
        n = 5
        batch = {
            "kb": torch.randn(n, 128), "mouse": torch.randn(n, 2 * INPUT_DIMS["mouse_dim"]),
            "pulse": torch.randn(n, 2 * INPUT_DIMS["pulse_dim"]), "face": torch.randn(n, 2 * INPUT_DIMS["face_dim"]),
            "ctx": torch.randn(n, INPUT_DIMS["ctx_dim"]), "net": torch.zeros(n, INPUT_DIMS["net_dim"]),
            "net_mask": torch.zeros(n), "profile_kb": torch.randn(n, 128), "profile_kb_mask": torch.ones(n),
            "profile_stats": torch.randn(n, INPUT_DIMS["profile_stats_dim"]),
            "mask": torch.tensor([[0, 1, 0, 0, 1, 1]] * n, dtype=torch.float32),
        }
        out = model.eval()(batch)
        self.assertEqual(out["nonowner"].shape, (n,))
        self.assertTrue(torch.isfinite(out["pressure"]).all())
        # A masked modality must not influence the output.
        batch2 = dict(batch, kb=torch.randn(n, 128) * 100, pulse=torch.randn_like(batch["pulse"]) * 100)
        self.assertTrue(torch.allclose(model(batch2)["nonowner"], out["nonowner"], atol=1e-5))

    def test_no_label_features(self):
        for name in CONTEXT_FEATURES:
            for bad in ("stress", "hurry", "condition", "group", "survey", "chat", "n_req"):
                self.assertNotIn(bad, name)


@unittest.skipUnless((PROCESSED_ROOT / "sessions.parquet").exists(), "processed data not available")
class FusionDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sessions = load_windows(workers=16)
        cls.profiles = build_profiles(cls.sessions)

    def test_enrolment_and_probe_are_disjoint(self):
        for sw in self.sessions.values():
            if sw.condition != "calm_1" or sw.split_ms is None:
                continue
            self.assertFalse((enrol_mask(sw) & probe_mask(sw)).any())
            # enrolment windows end before the split, probe windows start after it
            self.assertTrue((sw.starts[enrol_mask(sw)] + 10_000 <= sw.split_ms).all())
            self.assertTrue((sw.starts[probe_mask(sw)] >= sw.split_ms).all())

    def test_folds_split_people(self):
        people = sorted({s.participant for s in self.sessions.values()})
        for train, val, test in person_folds(people, self.profiles, 5, seed=0):
            self.assertFalse(set(train) & set(val) or set(train) & set(test) or set(val) & set(test))
            pairs = make_pairs(self.sessions, self.profiles, set(test))
            for p in pairs:
                self.assertIn(self.sessions[p.session_id].participant, test)
                self.assertIn(p.profile, test)

    def test_pair_labels(self):
        pairs = make_pairs(self.sessions, self.profiles, {s.participant for s in self.sessions.values()})
        for p in pairs:
            sw = self.sessions[p.session_id]
            if p.nonowner == 0:
                self.assertEqual(sw.participant, p.profile)
                self.assertNotEqual(sw.condition, "intruder")
                self.assertEqual(p.pressure, int(sw.condition == "scam"))
            else:
                self.assertNotEqual(sw.participant, p.profile)
                self.assertEqual(p.pressure_valid, 0)

    def test_tensors_finite(self):
        people = {s.participant for s in self.sessions.values()}
        pairs = make_pairs(self.sessions, self.profiles, people)[:50]
        norm = Normalizer.fit(list(self.sessions.values()))
        arrays = pair_tensors(pairs, self.sessions, self.profiles, norm)
        for k, v in arrays.items():
            self.assertTrue(np.isfinite(v).all(), k)
        model = FusionTransformer(**INPUT_DIMS, **CONFIG).eval()
        with torch.no_grad():
            out = model(to_torch(arrays, "cpu"))
        self.assertTrue(torch.isfinite(out["nonowner"]).all())


if __name__ == "__main__":
    unittest.main()
