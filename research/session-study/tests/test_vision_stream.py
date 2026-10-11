"""Tests for timestamped signal boundaries, gaps, and pulse recovery."""
import io
import json
from types import SimpleNamespace
import unittest

import numpy as np

from preprocessing.rppg import PulseSession, UniformCropSampler, normalize_frames, pulse_spectrum
from preprocessing.vision import face_box, posture_metrics


class FakeRunner:
    config = SimpleNamespace(pulse_fps=30.0, pulse_window_frames=128, pulse_stride_frames=96,
                             pulse_batch_size=3, min_face_fraction=0.95, minimum_hr_seconds=5.0,
                             hr_history_seconds=10.0, hr_update_seconds=0.5)
    def predict(self, windows):
        return np.stack([np.sin(np.arange(128) / 30 * 2 * np.pi * 1.2) for _ in windows])


class VideoSignalTests(unittest.TestCase):
    def test_uniform_sampler_keeps_video_clock_and_masks_large_gap(self):
        samples = []
        sampler = UniformCropSampler(10, 0.15, 2, lambda *args: samples.append(args))
        dark = np.zeros((2, 2, 3), dtype=np.uint8)
        light = np.full((2, 2, 3), 100, dtype=np.uint8)
        sampler.feed(0, dark, True)
        sampler.feed(0.12, light, True)
        sampler.feed(0.6, light, False)
        self.assertEqual([sample[0] for sample in samples], list(range(7)))
        self.assertTrue(samples[1][2])
        self.assertTrue(samples[1][4])
        self.assertFalse(samples[1][3])
        self.assertTrue(82 <= samples[1][1][0, 0, 0] <= 84)
        self.assertTrue(all(not sample[2] for sample in samples[2:6]))
        self.assertTrue(samples[6][2])

    def test_signal_coverage_for_short_and_long_recordings(self):
        for length in (1, 15, 16, 32, 127, 128, 129, 192, 223, 224, 800):
            with self.subTest(length=length):
                output, windows = io.StringIO(), io.StringIO()
                session = PulseSession(FakeRunner(), output, windows)
                image = np.full((2, 2, 3), 20, dtype=np.uint8)
                for i in range(length):
                    session.feed(i, image + (i % 20), True, True, False)
                summary = session.finish()
                rows = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(len(rows), length)
                self.assertEqual([row['sample_index'] for row in rows], list(range(length)))
                self.assertEqual(summary['pulse_samples'], length)
                self.assertEqual(rows[-1]['video_seconds'], (length - 1) / 30)
                if length < 16:
                    self.assertTrue(all(not row['pulse_valid'] for row in rows))
                else:
                    self.assertTrue(all(row['pulse_valid'] for row in rows))

    def test_missing_face_does_not_invent_a_waveform(self):
        output, windows = io.StringIO(), io.StringIO()
        session = PulseSession(FakeRunner(), output, windows)
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        for i in range(256):
            session.feed(i, image, False, False, False)
        session.finish()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 256)
        self.assertTrue(all(row['heart_rate_bpm'] is None and row['pulse_value'] is None for row in rows))

    def test_constant_video_does_not_produce_a_model_waveform(self):
        output, windows = io.StringIO(), io.StringIO()
        session = PulseSession(FakeRunner(), output, windows)
        image = np.full((2, 2, 3), 42, dtype=np.uint8)
        for i in range(300):
            session.feed(i, image, True, True, False)
        session.finish()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(all(not row['pulse_valid'] for row in rows))
        self.assertTrue(all(row['heart_rate_bpm'] is None for row in rows))
        statuses = [json.loads(line)['status'] for line in windows.getvalue().splitlines()]
        self.assertTrue(all(status == 'constant_face_crop' for status in statuses))

    def test_diffnormalization_is_finite_with_constant_rgb(self):
        result = normalize_frames(np.full((16, 2, 2, 3), 127, dtype=np.uint8))
        self.assertEqual(result.shape, (16, 2, 2, 3))
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(float(np.abs(result).sum()), 0)

    def test_difference_signal_recovers_known_rate(self):
        seconds = np.arange(300) / 30
        pulse = np.sin(2 * np.pi * 1.2 * seconds)
        difference = np.diff(pulse, prepend=pulse[0])
        result = pulse_spectrum(difference, 30)
        self.assertAlmostEqual(result['heart_rate_bpm'], 72, delta=1)
        self.assertGreater(result['spectral_concentration'], 0.6)

    def test_pose_requires_visible_geometry(self):
        self.assertIsNone(posture_metrics([], 640, 480))
        points = [[0, 0, 0, 0, 0] for _ in range(33)]
        self.assertIsNone(posture_metrics(points, 640, 480))


if __name__ == '__main__':
    unittest.main()
