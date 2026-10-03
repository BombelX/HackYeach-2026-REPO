import unittest
import numpy as np
from camera_estimator import estimate_bpm


class PulseTests(unittest.TestCase):
    def differences(self, bpm, seconds=10, fs=30):
        t = np.arange(int(seconds * fs) + 1) / fs
        return np.diff(np.sin(2 * np.pi * bpm / 60 * t), prepend=0)

    def test_known_frequencies(self):
        for bpm in (54, 72, 96, 138):
            with self.subTest(bpm=bpm):
                self.assertAlmostEqual(estimate_bpm(self.differences(bpm), 30), bpm, delta=2)

    def test_invalid_or_insufficient_signal(self):
        for values, fs in (([], 30), ([1], 30), (np.zeros(301), 30),
                           (np.full(301, np.nan), 30), (np.full(301, np.inf), 30),
                           (self.differences(72, 1), 30), (np.zeros(301), float('nan'))):
            with self.subTest(fs=fs, length=len(values)):
                self.assertIsNone(estimate_bpm(values, fs))

    def test_prior_does_not_select_spectral_slope(self):
        self.assertAlmostEqual(estimate_bpm(self.differences(96), 30, prior=72), 96, delta=2)

    def test_reacquires_stronger_peak(self):
        values = self.differences(72) + 5 * self.differences(120)
        self.assertAlmostEqual(estimate_bpm(values, 30, prior=72), 120, delta=2)
