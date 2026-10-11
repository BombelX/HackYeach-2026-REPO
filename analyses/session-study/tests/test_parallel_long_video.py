"""Regression tests for disjoint video cores and independent pulse histories.

Fixtures represent already-extracted model parts. No decoder, model checkpoint
or GPU is needed to verify that merging preserves the measured source clock.
"""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from preprocessing.alignment import resample_numeric
from preprocessing.vision import VisionConfig
from scripts.parallel_long_video import _merge_parts, _read_rows, _segments, _stream_sha256, _cache_artifacts_sha256, _implementation_sha256


class ParallelMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="parallel-merge-test-")
        self.root = Path(self.temp.name)
        self.output = self.root / "merged"
        self.output.mkdir()
        self.config = VisionConfig()
        # A nonzero source origin and fractional final core exercise both clocks.
        self.origin = 2.013
        self.metadata = {
            "pts_start_seconds": self.origin,
            "pts_end_seconds": self.origin + 6.5,
            "duration_seconds": 6.5,
            "unique_packet_pts": [self.origin + i / 10 for i in range(66)],
        }
        self.parts = self._make_parts()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_rows(path, rows):
        path.write_text("".join(json.dumps(row, allow_nan=False) + "\n" for row in rows),
                        encoding="utf-8")

    def _make_parts(self):
        # Short, stride-aligned cores keep fixtures small; model warmup quality
        # is verified separately by the real-model smoke test.
        specs = _segments(self.metadata, 3.2, 3.2, 3.2, self.config)
        parts = []
        source_pts = self.metadata["unique_packet_pts"]
        for spec in specs:
            folder = self.root / f"part-{spec['part_id']}"
            folder.mkdir(exist_ok=True)
            warm = spec["warmup_start_sample"]
            decoded_stop = int(round(spec["decode_end_seconds"] * 30))
            pulse = []
            for global_index in range(warm, decoded_stop + 1):
                local_index = global_index - warm
                pulse.append({
                    "sample_index": local_index,
                    "video_seconds": local_index / 30,
                    "pulse_valid": True,
                    "face_crop_valid": True,
                    "face_box_observed": True,
                    "temporal_interpolated": False,
                    "model_padded_window": False,
                    "pulse_difference": 0.25,
                    "pulse_value": float(1000 * spec["part_id"] + local_index),
                    # Each model part deliberately reuses the same local ID.
                    "pulse_segment_id": 1,
                    "pulse_window_seconds": 10.0,
                    "heart_rate_bpm": 72.0 + spec["part_id"],
                    "heart_rate_status": "estimate",
                    "spectral_concentration": 0.8,
                })
            frames = []
            warm_seconds = spec["warmup_start_seconds"]
            for source_index, stamp in enumerate(source_pts):
                seconds = stamp - self.origin
                if (source_index % 2 == 0 and
                        warm_seconds - 1e-7 <= seconds <= spec["decode_end_seconds"] + 1e-7):
                    frames.append({
                        "pts_seconds": stamp,
                        "video_pts_seconds": stamp,
                        "video_seconds": seconds - warm_seconds,
                        "pts": round(stamp * 1_000_000),
                        "time_base_numerator": 1,
                        "time_base_denominator": 1_000_000,
                        "frame_index": source_index - round(warm_seconds * 10),
                        "face_detected": True,
                        "pose_detected": True,
                    })
            self._write_rows(folder / "pulse.jsonl", pulse)
            self._write_rows(folder / "video_frames.jsonl", frames)
            self._write_rows(folder / "pulse_windows.jsonl", [])
            core_count = sum(spec["core_start_seconds"] - 1e-7 <= stamp - self.origin <
                             spec["core_end_seconds"] - 1e-7 for stamp in source_pts)
            parts.append({
                "spec": spec,
                "output_dir": str(folder),
                "window_stats": {"core_decoded_frames": core_count, "core_duplicate_pts": 0},
            })
        return parts

    def _merge(self, parts=None):
        return _merge_parts(self.parts if parts is None else parts, self.output,
                            self.metadata, self.config)

    def _pulse(self):
        return list(_read_rows(self.output / "pulse.jsonl"))

    def _part_rows(self, part_id, filename="pulse.jsonl"):
        path = Path(self.parts[part_id]["output_dir"]) / filename
        return path, list(_read_rows(path))

    def test_cores_keep_every_sample_once_and_discard_overlapping_context(self):
        counts = self._merge(list(reversed(self.parts)))
        pulse = self._pulse()
        self.assertEqual([row["sample_index"] for row in pulse], list(range(196)))
        self.assertEqual([row["video_seconds"] for row in pulse], [i / 30 for i in range(196)])
        self.assertEqual([row["model_history_segment_id"] for row in pulse],
                         [0] * 96 + [1] * 96 + [2] * 4)
        self.assertEqual(counts["pulse_samples"], 196)
        self.assertEqual(counts["valid_pulse_samples"], 196)
        self.assertEqual(counts["decoded_frames"], 66)
        self.assertEqual(counts["feature_frames"], 33)
        self.assertEqual(pulse[-1]["video_seconds"], 6.5)

    def test_successful_merge_emits_reproducible_coverage_validation(self):
        validation = {}
        counts = _merge_parts(self.parts, self.output, self.metadata, self.config,
                              validation=validation)
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["errors"], [])
        self.assertEqual(validation["pulse_samples"], validation["expected_pulse_samples"])
        self.assertEqual(validation["decoded_unique_frames"], validation["expected_decoded_unique_frames"])
        self.assertEqual(validation["frames"], validation["expected_feature_frames"])
        self.assertEqual(validation["pulse_value_seam_gaps"], 2)
        self.assertEqual(validation["first_sample_index"], 0)
        self.assertEqual(validation["last_sample_index"], 195)
        self.assertEqual(validation["padded_interior_samples"], 0)
        self.assertTrue(validation["actual_feature_pts_match_single_pass_schedule"])
        self.assertEqual(len(validation["core_boundaries"]), 3)

    def test_invalid_signal_and_early_bpm_are_rejected(self):
        for mode in ("invalid", "early_bpm"):
            with self.subTest(mode=mode):
                self.parts = self._make_parts()
                path, rows = self._part_rows(0)
                if mode == "invalid":
                    rows[0]["pulse_valid"] = False
                    expected = "Invalid pulse sample contains"
                else:
                    rows[0]["pulse_window_seconds"] = 4.9
                    expected = "BPM sample emitted before"
                self._write_rows(path, rows)
                with self.assertRaisesRegex(ValueError, expected):
                    self._merge()

    def test_streaming_sha_matches_known_video_bytes(self):
        import hashlib
        payload = b"video-fragment" * 100000
        path = self.root / "source.webm"
        path.write_bytes(payload)
        self.assertEqual(_stream_sha256(path), hashlib.sha256(payload).hexdigest())

    def test_cache_manifest_detects_changed_content_even_at_same_byte_size(self):
        names = ("video_frames.jsonl", "pulse.jsonl", "pulse_windows.jsonl", "video_summary.json")
        for name in names:
            (self.output / name).write_text('{"value":1}\n')
        original = _cache_artifacts_sha256(self.output)
        (self.output / "pulse.jsonl").write_text('{"value":2}\n')
        changed = _cache_artifacts_sha256(self.output)
        self.assertNotEqual(original["pulse.jsonl"], changed["pulse.jsonl"])
        self.assertEqual(original["video_summary.json"], changed["video_summary.json"])
        self.assertEqual(set(original), set(names))

    def test_package_manifest_matches_main_pipeline_digest(self):
        import hashlib
        from scripts.parallel_long_video import ROOT
        expected = hashlib.sha256(b"".join(path.read_bytes() for path in
                                  sorted((ROOT / "preprocessing").glob("*.py")))).hexdigest()
        self.assertEqual(_implementation_sha256(), expected)

    def test_missing_or_duplicate_first_sample_at_a_core_seam_is_rejected(self):
        for mode in ("missing", "duplicate"):
            with self.subTest(mode=mode):
                self.parts = self._make_parts()
                path, rows = self._part_rows(1)
                first = self.parts[1]["spec"]["core_start_sample"]
                boundary = next(i for i, row in enumerate(rows) if row["sample_index"] == first)
                if mode == "missing":
                    rows.pop(boundary)
                else:
                    rows.insert(boundary, dict(rows[boundary]))
                self._write_rows(path, rows)
                with self.assertRaisesRegex(ValueError, "Lost/duplicate pulse sample at a core seam"):
                    self._merge()

    def test_missing_final_sample_is_rejected(self):
        path, rows = self._part_rows(2)
        self._write_rows(path, rows[:-1])
        with self.assertRaisesRegex(ValueError, "Final pulse coverage mismatch"):
            self._merge()

    def test_independent_history_ids_and_boundary_null_block_scalar_interpolation(self):
        self._merge()
        pulse = self._pulse()
        self.assertEqual({row["pulse_segment_id"] for row in pulse[:96]}, {1})
        self.assertEqual({row["pulse_segment_id"] for row in pulse[96:192]}, {2})
        self.assertEqual({row["pulse_segment_id"] for row in pulse[192:]}, {3})
        self.assertEqual([row["sample_index"] for row in pulse if row["core_boundary"]],
                         [0, 96, 192])
        self.assertEqual(pulse[0]["pulse_value"], 0.0)
        for index in (96, 192):
            self.assertIsNone(pulse[index]["pulse_value"])
            self.assertEqual(pulse[index]["pulse_value_status"], "model_history_boundary")
            self.assertTrue(pulse[index]["pulse_valid"])
            self.assertEqual(pulse[index]["pulse_difference"], 0.25)
            self.assertIsNotNone(pulse[index]["heart_rate_bpm"])
            self.assertTrue(pulse[index]["model_history_independent"])
            self.assertIsNotNone(pulse[index + 1]["pulse_value"])
            self.assertEqual(pulse[index + 1]["pulse_value_status"], "relative_part_integral")
        # A large enough interpolation allowance would cross the abrupt integral
        # reset if the explicit boundary NaN were ever dropped.
        times = np.asarray([row["video_seconds"] * 1000 for row in pulse])
        values = np.asarray([np.nan if row["pulse_value"] is None else row["pulse_value"]
                             for row in pulse])
        grid = np.asarray([94.5, 95.5, 96, 96.5, 97.5]) / 30 * 1000
        sampled = resample_numeric(times, values, grid, max_gap_ms=100)
        self.assertEqual(sampled["valid"].tolist(), [True, False, False, False, True])
        self.assertEqual(sampled["interpolated"].tolist(), [True, False, False, False, True])
        self.assertTrue(np.isnan(sampled["values"][1:4]).all())

    def test_valid_padded_sample_in_any_nonfinal_core_is_rejected(self):
        for part_id in (0, 1):
            with self.subTest(part_id=part_id):
                self.parts = self._make_parts()
                path, rows = self._part_rows(part_id)
                spec = self.parts[part_id]["spec"]
                index = spec["core_start_sample"] - spec["warmup_start_sample"] + 1
                row = next(row for row in rows if row["sample_index"] == index)
                row["model_padded_window"] = True
                self._write_rows(path, rows)
                with self.assertRaisesRegex(ValueError, "Padded neural window leaked into an interior core"):
                    self._merge()

    def test_final_padded_estimate_retains_its_quality_flag(self):
        path, rows = self._part_rows(2)
        rows[-1]["model_padded_window"] = True
        self._write_rows(path, rows)
        self._merge()
        self.assertTrue(self._pulse()[-1]["model_padded_window"])
        self.assertTrue(self._pulse()[-1]["pulse_valid"])

    def test_shifted_source_pts_and_frame_indices_survive_warmup_context(self):
        path, rows = self._part_rows(2, "video_frames.jsonl")
        # An artificial timestamp within warmup must never reach core output.
        synthetic = dict(rows[0], pts_seconds=self.origin + 3.25, frame_index=99999)
        self._write_rows(path, [synthetic] + rows)
        self._merge()
        frames = list(_read_rows(self.output / "video_frames.jsonl"))
        expected = self.metadata["unique_packet_pts"][::2]
        self.assertEqual([row["pts_seconds"] for row in frames], expected)
        self.assertEqual([row["video_pts_seconds"] for row in frames], expected)
        self.assertEqual([row["frame_index"] for row in frames], list(range(0, 66, 2)))
        self.assertEqual(frames[-1]["frame_index"], 64)
        self.assertEqual(frames[-1]["segment_frame_index"], 32)
        self.assertEqual(frames[-1]["model_history_segment_id"], 2)
        for row in frames:
            self.assertAlmostEqual(row["video_seconds"], row["pts_seconds"] - self.origin)
        pulse = self._pulse()
        self.assertEqual([row["pts_seconds"] for row in pulse],
                         [self.origin + i / 30 for i in range(196)])
        self.assertEqual(pulse[-1]["pts_seconds"], self.origin + 6.5)

    def test_synthetic_or_unknown_timestamp_in_core_is_rejected(self):
        path, rows = self._part_rows(0, "video_frames.jsonl")
        synthetic = dict(rows[0], pts_seconds=self.origin + 0.05, frame_index=99999)
        self._write_rows(path, [rows[0], synthetic] + rows[1:])
        with self.assertRaisesRegex(ValueError, "synthetic or unknown source frame entered the core"):
            self._merge()

    def test_decoded_source_frame_loss_is_rejected(self):
        self.parts[1]["window_stats"]["core_decoded_frames"] -= 1
        with self.assertRaisesRegex(ValueError, "Core decoded-frame coverage does not match"):
            self._merge()


if __name__ == "__main__":
    unittest.main()
