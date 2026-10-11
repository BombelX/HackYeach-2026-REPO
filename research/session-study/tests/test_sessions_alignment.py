from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import numpy as np

from preprocessing.alignment import SessionClock, infer_video_alignment, regular_grid, resample_numeric
from preprocessing.sessions import SessionRecord, concatenate_chunks, group_for, inventory, read_jsonl


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "sessions").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def session(self, name="a", condition="calm_1", *, ended=2):
        folder = self.root / "sessions" / name
        (folder / "video").mkdir(parents=True)
        (folder / "meta.json").write_text(json.dumps({"condition": condition, "ended_at": ended, "started_at": 1}))
        return folder

    def test_grouping_and_context_keep_calibration_and_unknown(self):
        for name, condition in (("a", "calm_3"), ("b", "calibration"), ("c", "future_scenario")):
            folder = self.session(name, condition)
            (folder / "trace.har").write_text('{"log":{"entries":[]}}')
        found = inventory(self.root)
        self.assertEqual([r.group for r in found], ["calm", None, None])
        self.assertEqual([r.status for r in found], ["no_video", "excluded_condition", "excluded_condition"])
        self.assertTrue(all(any(p.suffix == ".har" for p in r.context_paths) for r in found))
        self.assertIsNone(group_for("calming"))

    def test_fragment_concatenation_uses_numeric_order_and_single_header(self):
        folder = self.session()
        chunks = [b"\x1a\x45\xdf\xa3header", b"fragment", b"finalfragment"]
        for number, content in enumerate(chunks):
            (folder / "video" / f"{number:04d}.webm").write_bytes(content)
        record, = inventory(self.root)
        self.assertEqual(record.status, "ready")
        joined = concatenate_chunks(record, self.root / "joined.webm")
        self.assertEqual(joined.read_bytes(), b"".join(chunks))
        self.assertEqual(record.as_manifest()["chunks"], 3)
        with self.assertRaises(ValueError):
            concatenate_chunks(record, record.chunk_paths[0])

    def test_missing_chunk_and_missing_header_are_explicit(self):
        folder = self.session()
        (folder / "video" / "0001.webm").write_bytes(b"fragment")
        record, = inventory(self.root)
        self.assertEqual(record.status, "invalid_video_chunks")
        self.assertIn("missing_initial_container_header", record.warnings)
        with self.assertRaises(ValueError):
            concatenate_chunks(record, self.root / "joined.webm")

    def test_mp4_fragments_and_unfinished_session(self):
        folder = self.session(ended=None)
        (folder / "video" / "0000.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom")
        (folder / "video" / "0001.mp4").write_bytes(b"mdatfragment")
        record, = inventory(self.root)
        self.assertEqual(record.status, "incomplete_session")
        self.assertEqual(concatenate_chunks(record, self.root / "joined.mp4").read_bytes(),
                         b"\x00\x00\x00\x18ftypisommdatfragment")

    def test_db_sessions_without_folders_and_deleted_metadata(self):
        database = sqlite3.connect(self.root / "participants.sqlite")
        database.executescript("CREATE TABLE participants(id INTEGER,code TEXT,deleted_at REAL);"
                               "CREATE TABLE sessions(id TEXT,condition TEXT,order_index INTEGER,"
                               "started_at REAL,ended_at REAL,participant_id INTEGER);"
                               "INSERT INTO participants VALUES(1,'anonymous',NULL),(2,'deleted',0);"
                               "INSERT INTO sessions VALUES('no-source','scam',1,1,2,1),('deleted','scam',1,1,2,2);")
        database.close()
        deleted = self.session('deleted', 'scam')
        stale_meta = json.loads((deleted / 'meta.json').read_text())
        stale_meta['deleted_at'] = None
        (deleted / 'meta.json').write_text(json.dumps(stale_meta))
        records = {r.session_id: r for r in inventory(self.root)}
        self.assertEqual(records['no-source'].status, 'no_source')
        self.assertEqual(records['deleted'].status, 'deleted')

    def test_malformed_jsonl_is_not_silently_ignored(self):
        path = self.root / "events.jsonl"
        path.write_text('{"t_perf":0}\ninvalid\n[]\n')
        with self.assertRaises(ValueError):
            read_jsonl(path)
        issues = []
        self.assertEqual(read_jsonl(path, strict=False, issues=issues), [{"t_perf": 0}])
        self.assertEqual(len(issues), 2)


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.record = SessionRecord('test', 'calm_1', 'calm', Path(self.temp.name), [], 'no_video',
                                    {"started_at": 1000, "ended_at": 1015})
        self.events = [{"t_perf": 100, "t_epoch": 1005100, "type": "keydown"},
                       {"t_perf": 200, "t_epoch": 1005200, "type": "keyup"}]
        self.sync = [{"type": "clock_sync", "t_perf": 100, "t_epoch": 1005100,
                      "rtt_ms": 20, "offset_ms": -5000, "server_epoch_ms": 1000110}]
        self.clock = SessionClock.from_session(self.record, events=self.events, net=self.sync, face=[])

    def tearDown(self):
        self.temp.cleanup()

    def test_server_offset_sign_and_monotonic_hold_duration(self):
        before, after = (self.clock(row) for row in self.events)
        self.assertEqual(before['t_server_epoch_ms'], 1000100)
        self.assertEqual(before['t_session_ms'], 100)
        self.assertEqual(after['t_session_ms'] - before['t_session_ms'], 100)
        self.assertEqual(before['t_client_epoch_ms'], 1005100)
        self.assertEqual(before['status'], 'synchronized_monotonic')
        self.assertEqual(self.clock.uncertainty_ms, 10)

    def test_server_receive_epoch_not_double_corrected(self):
        mapped = self.clock({"type": "video_chunk", "t_epoch": 1000300})
        self.assertEqual(mapped['t_session_ms'], 300)
        self.assertEqual(mapped['status'], 'server_epoch')

    def test_ping_end_epoch_does_not_shift_browser_origin(self):
        ping = {"type": "ping", "t_perf": 100, "t_epoch": 1005600,
                "rtt_ms": 500, "server_epoch_ms": 1000350}
        clock = SessionClock.from_session(self.record, events=self.events, net=[ping], face=[])
        self.assertEqual(clock.browser_origin_ms, 1005000)
        self.assertEqual(clock(self.events[0])['t_session_ms'], 100)
        self.assertEqual(clock.source, 'ping_midpoint')

    def test_high_rtt_jitter_cannot_change_event_intervals(self):
        bad = {"type": "clock_sync", "t_perf": 30100, "t_epoch": 1035100,
               "rtt_ms": 2000, "server_epoch_ms": 1031350}
        clock = SessionClock.from_session(self.record, events=self.events, net=[*self.sync, bad], face=[])
        self.assertEqual(clock(self.events[0])['t_session_ms'], 100)
        self.assertEqual(clock(self.events[1])['t_session_ms'], 200)

    def test_missing_sync_and_zero_timestamp_are_visible(self):
        clock = SessionClock.from_session(self.record, events=[{'t_perf': 0, 't_epoch': 1000000}], net=[], face=[])
        self.assertEqual(clock({'t_perf': 0})['t_session_ms'], 0)
        self.assertEqual(clock({'t_perf': 0})['status'], 'unsynchronized_client_clock')
        self.assertIsNone(clock({'t_perf': 0})['uncertainty_ms'])
        self.assertEqual(clock({})['status'], 'missing_timestamp')

    def test_old_video_anchor_has_interval_and_no_five_second_assumption(self):
        net = [{'type': 'video_chunk', 'index': 0, 't_epoch': 1009400},
               {'type': 'video_chunk', 'index': 1, 't_epoch': 1014900}]
        video = infer_video_alignment(self.record, self.clock, 0.25, 10.25, net=net)
        self.assertEqual(video.quality, 'approx_session_start')
        self.assertEqual(video.start_interval_server_ms, (1000000, 1005000))
        self.assertEqual(video.uncertainty_ms, 5000)
        self.assertEqual(video.map_pts(1.25)['t_session_ms'], 1000)

    def test_future_recorder_start_requested_is_still_estimated(self):
        self.record.meta['camera'] = {'recording_clock': {'t_perf': 300, 't_epoch': 1005300,
                                                           'marker': 'media_recorder_start_requested'}}
        video = infer_video_alignment(self.record, self.clock, 0.01, 10.01, net=[])
        self.assertEqual(video.quality, 'recording_start_requested')
        self.assertEqual(video.map_pts(1.01)['t_session_ms'], 1300)
        self.assertIsNone(video.uncertainty_ms)
        self.assertIn('first_encoded_frame_latency_not_measured', video.warnings)

    def test_explicit_pts_anchor_and_declared_uncertainty(self):
        video = infer_video_alignment(self.record, self.clock, 0, 10,
                                      {'t_perf': 100, 'pts_seconds': 2, 'uncertainty_ms': 15})
        self.assertEqual(video.map_pts(2)['t_session_ms'], 100)
        self.assertEqual(video.map_pts(3)['t_session_ms'], 1100)
        self.assertEqual(video.uncertainty_ms, 15)
        self.assertEqual(video.pts_start_seconds, 0)
        self.assertEqual(video.pts_anchor_seconds, 2)


class ResampleTests(unittest.TestCase):
    def test_missing_gaps_and_bounded_extrapolation_masks(self):
        result = resample_numeric([0, 100, 1000], [0, 1, 10], [-100, -50, 0, 50, 100, 500, 1000, 1050, 1100],
                                  max_gap_ms=200, max_extrapolation_ms=50)
        np.testing.assert_allclose(result['values'], [np.nan, -.5, 0, .5, 1, np.nan, 10, 10, np.nan], equal_nan=True)
        np.testing.assert_array_equal(result['observed'], [False, False, True, False, True, False, True, False, False])
        np.testing.assert_array_equal(result['interpolated'], [False, False, False, True, False, False, False, False, False])
        np.testing.assert_array_equal(result['extrapolated'], [False, True, False, False, False, False, False, True, False])
        self.assertTrue(result['missing'][5])
        self.assertEqual(result['gap_ms'][5], 900)

    def test_explicit_missing_rows_do_not_get_fabricated(self):
        result = resample_numeric([0, 100, 200], [[0, 0], [np.nan, 1], [2, 2]], [50, 100, 150], max_gap_ms=200)
        self.assertTrue(np.isnan(result['values'][:, 0]).all())
        np.testing.assert_allclose(result['values'][:, 1], [.5, 1, 1.5])
        self.assertTrue(result['observed'][1, 1])
        self.assertFalse(result['observed'][1, 0])

    def test_duplicate_timestamps_last_upload_wins(self):
        result = resample_numeric([100, 0, 100], [1, 0, 2], [0, 50, 100], max_gap_ms=100)
        np.testing.assert_allclose(result['values'], [0, 1, 2])

    def test_empty_stream_keeps_all_values_missing(self):
        result = resample_numeric([], np.empty((0, 3)), [0, 10], max_gap_ms=100)
        self.assertEqual(result['values'].shape, (2, 3))
        self.assertTrue(result['missing'].all())
        self.assertFalse(result['valid'].any())

    def test_grid_and_invalid_parameters(self):
        np.testing.assert_allclose(regular_grid(0, 100, 20), [0, 50, 100])
        with self.assertRaises(ValueError):
            resample_numeric([np.nan], [1], [0], max_gap_ms=100)
        with self.assertRaises(ValueError):
            regular_grid(10, 0, 30)


if __name__ == '__main__':
    unittest.main()
