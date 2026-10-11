import json
from pathlib import Path
import tempfile
import unittest

import pyarrow.parquet as pq

from preprocessing.pipeline import fingerprint, is_complete, process_session
from preprocessing.sessions import SessionRecord
from preprocessing.tables import align_vision, write_table
from preprocessing.alignment import VideoAlignment


class NoVideoExtractor:
    def extract(self, *args):
        raise AssertionError("A camera-free session must not decode video")


class StubEmbedder:
    def embed(self, prepared):
        return {"dimension": 128, "window_embeddings": [], "session_embedding": None,
                "mask": False, "status": "insufficient_keystrokes"}


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "raw" / "session"
        self.source.mkdir(parents=True)
        self.meta = {"started_at": 1000, "ended_at": 1001, "condition": "calm_1"}
        (self.source / "meta.json").write_text(json.dumps(self.meta))
        events = [dict(t_perf=10, t_epoch=1000010, type="stage_start", payload={"stage": "login"}),
                  dict(t_perf=20, t_epoch=1000020, type="input", payload={"data": "SECRET", "valueLength": 6})]
        (self.source / "events.jsonl").write_text("\n".join(json.dumps(x) for x in events))
        self.record = SessionRecord("session", "calm_1", "calm", self.source, [], "no_video", self.meta)
        self.config = {"force": False, "feature_fps": 5, "max_gap_ms": 500, "max_extrapolation_ms": 0}
        self.target = self.root / "outputs" / "session"

    def tearDown(self):
        self.temp.cleanup()

    def test_no_video_preserves_context_masks_and_numeric_markers(self):
        before = (self.source / "events.jsonl").read_bytes()
        result = process_session(self.record, self.target, self.config, NoVideoExtractor(), StubEmbedder())
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["keyboard_mask"])
        self.assertEqual(pq.read_table(self.target / "frames.parquet").num_rows, 0)
        self.assertEqual(pq.read_table(self.target / "network.parquet").num_rows, 0)
        marker_text = str(pq.read_table(self.target / "markers.parquet").to_pylist())
        self.assertNotIn("SECRET", marker_text)
        self.assertEqual((self.source / "events.jsonl").read_bytes(), before)
        self.assertEqual(json.loads((self.target / "context.json").read_text())["meta"], self.meta)
        self.assertTrue(is_complete(self.target, fingerprint(self.record, self.config)))

    def test_resume_requires_unchanged_source_and_artifacts(self):
        process_session(self.record, self.target, self.config, NoVideoExtractor(), StubEmbedder())
        result = process_session(self.record, self.target, self.config, NoVideoExtractor(), StubEmbedder())
        self.assertEqual(result["status"], "resumed")
        (self.target / "frames.parquet").unlink()
        self.assertFalse(is_complete(self.target, fingerprint(self.record, self.config)))

    def test_failure_keeps_previous_success(self):
        process_session(self.record, self.target, self.config, NoVideoExtractor(), StubEmbedder())
        before = (self.target / "summary.json").read_bytes()
        (self.source / "events.jsonl").write_text("invalid JSON")
        with self.assertRaises(ValueError):
            process_session(self.record, self.target, self.config, NoVideoExtractor(), StubEmbedder())
        self.assertEqual((self.target / "summary.json").read_bytes(), before)
        self.assertFalse(list(self.target.parent.glob(".stage-*")))

    def test_empty_nested_detection_can_be_written(self):
        path = self.root / "absent.parquet"
        write_table(path, [{"blendshapes": {}, "pose": [], "face_landmarks": []}], "session")
        self.assertEqual(pq.read_table(path).num_rows, 1)

    def test_force_does_not_change_fingerprint(self):
        self.assertEqual(fingerprint(self.record, self.config),
                         fingerprint(self.record, {**self.config, "force": True}))

    def test_worker_count_does_not_change_numerical_fingerprint(self):
        self.assertEqual(fingerprint(self.record, {**self.config, "workers_per_gpu": 2}),
                         fingerprint(self.record, {**self.config, "workers_per_gpu": 8}))

    def test_later_rows_do_not_lose_optional_columns(self):
        path = self.root / "variable.parquet"
        write_table(path, [{"x": 1}, {"x": 2, "optional": 3}], "session")
        self.assertEqual(pq.read_table(path).to_pylist()[1]["optional"], 3)

    def test_new_chunk_invalidates_the_source_fingerprint(self):
        original = fingerprint(self.record, self.config)
        (self.source / "video").mkdir()
        (self.source / "video" / "0001.webm").write_bytes(b"new fragment")
        self.assertNotEqual(original, fingerprint(self.record, self.config))

    def test_pulse_window_bounds_and_extraction_status_survive_alignment(self):
        alignment = VideoAlignment(5, 1000000, 999000, "estimated", 50, decoded_start_pts_seconds=1)
        rows = align_vision([{"video_seconds_start": 10, "video_seconds_end": 14,
                              "status": "low_face_coverage"}], alignment)
        self.assertEqual(rows[0]["t_session_ms_start"], 7000)
        self.assertEqual(rows[0]["t_session_ms_end"], 11000)
        self.assertEqual(rows[0]["extraction_status"], "low_face_coverage")
        self.assertEqual(rows[0]["alignment_status"], "estimated")


if __name__ == "__main__":
    unittest.main()
