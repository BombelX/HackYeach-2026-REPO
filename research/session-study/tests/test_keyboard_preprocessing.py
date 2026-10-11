"""Timing, training compatibility, missing-data and coalesced-sample contracts."""
import math
import unittest

import numpy as np

from preprocessing.input_events import extract_mouse
from preprocessing.keyboard import aalto_features, browser_key, extract_keyboard


def event(kind, t, **payload):
    return {"type": kind, "t_perf": t, "t_epoch": 1700000000000 + t,
            "payload": {"code": "KeyA", "key": "a", "field": "test", **payload}}


def mapper(row):
    return {"t_session_ms": row["t_perf"] - 10,
            "t_client_epoch_ms": row["t_epoch"],
            "t_server_epoch_ms": row["t_epoch"] + 20,
            "status": "clock_sync", "uncertainty_ms": 2}


class KeyboardPreprocessingTests(unittest.TestCase):
    def test_timing_features_preserve_negative_flight_and_float16_training_precision(self):
        actual = aalto_features(140, 195, "a", 100, 160)
        expected = np.asarray([math.log1p(55), math.log1p(40), -math.log1p(20), 1, 0, 0, 0, 0], dtype=np.float16).astype(np.float32)
        np.testing.assert_array_equal(actual, expected)
        clipped = aalto_features(9000, 19000, "a", 0, 10000)
        self.assertEqual(clipped[0], np.float32(np.float16(math.log1p(3000))))
        self.assertEqual(clipped[1], np.float32(np.float16(math.log1p(3000))))

    def test_historical_aalto_letter_flags_and_legacy_keycode(self):
        key_id, letter, source = browser_key({"key": "Backspace", "code": "Backspace"})
        self.assertEqual((key_id, letter), (9, "BKSP"))
        self.assertEqual(aalto_features(0, 10, letter)[4], 0)
        self.assertEqual(aalto_features(0, 10, letter)[7], 1)
        self.assertEqual(aalto_features(0, 10, " ")[6], 0)
        self.assertEqual(aalto_features(0, 10, " ")[7], 1)
        self.assertEqual(aalto_features(0, 10, "SHIFT")[5], 1)
        self.assertIn("inferred", source)
        self.assertEqual(browser_key({"key": "a", "code": "KeyA", "keyCode": 65})[0], 66)

    def test_rollover_release_pairing_uses_physical_key_and_keeps_repeat_events(self):
        rows = [event("keydown", 100), event("keydown", 110, repeat=True),
                event("keydown", 140, code="KeyB", key="b"),
                event("keyup", 160), event("keyup", 195, code="KeyB", key="b")]
        result = extract_keyboard(rows, mapper)
        self.assertEqual(len(result["event_rows"]), 5)
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(result["rows"][0]["release_valid"])
        self.assertEqual(result["rows"][1]["f3"], 1)
        self.assertLess(result["rows"][1]["f2"], 0)
        self.assertEqual(result["rows"][0]["t_session_ms"], 90)
        self.assertEqual(result["summary"]["auto_repeat_excluded_from_embedding"], 1)
        self.assertFalse(any("key" in row or "code" in row or "payload" in row for row in result["rows"] + result["event_rows"]))

    def test_mask_lengths_short_tail_and_missing_release(self):
        rows = []
        for i in range(103):
            rows.append(event("keydown", i * 30))
            if i != 102:
                rows.append(event("keyup", i * 30 + 20))
        result = extract_keyboard(rows)
        self.assertEqual(len(result["windows"]), 2)
        first, tail = result["windows"]
        self.assertEqual((first["valid_length"], tail["valid_length"]), (96, 7))
        self.assertEqual(first["status"], "ready")
        self.assertEqual(tail["status"], "insufficient_keystrokes")
        self.assertEqual(tail["mask"].sum(), 7)
        self.assertTrue(np.all(tail["key_id"][7:] == 0))
        self.assertFalse(result["rows"][-1]["release_valid"])
        self.assertEqual(result["rows"][-1]["f0"], 0)
        self.assertEqual(result["summary"]["unreleased_keydown"], 1)

    def test_field_and_clock_reset_begin_new_feature_segment(self):
        rows = [event("keydown", 100), event("keyup", 120),
                event("keydown", 140, field="other"), event("keyup", 160, field="other"),
                {**event("keydown", 50, field="other"), "t_epoch": 1700000000200}]
        result = extract_keyboard(rows)
        self.assertEqual(len(result["windows"]), 3)
        self.assertEqual([s["f1"] for s in result["rows"]], [0, 0, 0])

    def test_coalesced_pointer_times_map_samples_and_preserve_invalid_sample(self):
        pointer = {"type": "pointermove", "t_perf": 100, "t_epoch": 1700000000100,
                   "payload": {"pointerId": 1, "pointerType": "mouse", "field": "test",
                   "samples": [{"t": 90, "x": 1, "y": 2, "pressure": 0},
                               {"t": 98, "x": 3, "y": 4},
                               {"t": 1700000000000, "x": 5, "y": 6}]}}
        result = extract_mouse([pointer], mapper)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["rows"][0]["t_session_ms"], 80)
        self.assertEqual(result["rows"][1]["t_session_ms"], 88)
        self.assertEqual(result["rows"][2]["t_session_ms"], 90)
        self.assertFalse(result["rows"][2]["sample_timestamp_valid"])
        self.assertEqual(result["rows"][2]["source_sample_t_perf_ms"], 1700000000000)
        self.assertEqual(result["summary"]["sample_time_event_fallback"], 1)
        self.assertEqual(result["feature_manifest"]["model_status"], "not_trained")

    def test_missing_pointer_coordinates_are_null_and_wheel_keeps_delta_mode(self):
        result = extract_mouse([event("pointermove", 100),
                                event("wheel", 110, deltaY=2, deltaMode=1)])
        self.assertFalse(result["rows"][0]["mask"])
        self.assertIsNone(result["rows"][0]["x"])
        self.assertTrue(result["rows"][1]["mask"])
        self.assertEqual(result["rows"][1]["delta_mode"], 1)
        self.assertEqual(result["rows"][1]["delta_y"], 2)


if __name__ == "__main__":
    unittest.main()
