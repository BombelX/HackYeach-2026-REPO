#!/usr/bin/env python3
"""Validate committed session outputs without loading images or model weights."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from preprocessing.pipeline import fingerprint, is_complete
from preprocessing.sessions import inventory
from preprocessing.tables import write_json


def validate(data: Path, output: Path) -> dict:
    records = {r.session_id: r for r in inventory(data)}
    groups = Counter()
    rows = Counter()
    devices = Counter()
    statuses = Counter()
    errors = []
    total_seconds = 0
    masks = Counter()
    for path in sorted(output.glob("sessions/*/*/summary.json")):
        summary = json.loads(path.read_text())
        sid = summary["session_id"]
        record = records.get(sid)
        try:
            if record is None:
                raise ValueError("source session no longer exists")
            if not is_complete(path.parent, fingerprint(record, summary["config"])):
                raise ValueError("source fingerprint or artifact size mismatch")
            context = json.loads((path.parent / "context.json").read_text())
            groups[summary["group"]] += 1
            for name, count in summary["rows"].items():
                actual = pq.read_metadata(path.parent / name).num_rows
                if actual != count:
                    raise ValueError(name + " row count mismatch")
                rows[name] += count
            video = summary["video"]
            if video.get("decoded_frames"):
                devices[video["device"]] += 1
                total_seconds += video["duration_seconds"]
                frames = pq.read_table(path.parent / "frames.parquet", columns=["t_session_ms", "pts_seconds"])
                for column in frames.column_names:
                    values = frames[column].to_numpy()
                    if not np.isfinite(values).all() or (len(values) > 1 and not (np.diff(values) > 0).all()):
                        raise ValueError("invalid/non-monotonic " + column)
                pulse = pq.read_table(path.parent / "pulse.parquet",
                                      columns=["pulse_valid", "pulse_value", "heart_rate_bpm", "t_session_ms"])
                pulse_time = pulse["t_session_ms"].to_numpy()
                if len(pulse_time) > 1 and not (np.diff(pulse_time) > 0).all():
                    raise ValueError("non-monotonic pulse timeline")
                values = pulse.to_pylist()
                if any(not r["pulse_valid"] and (r["pulse_value"] is not None or r["heart_rate_bpm"] is not None)
                       for r in values):
                    raise ValueError("invalid pulse has fabricated signal/HR")
                masks["video"] += 1
                masks["hr"] += any(r["heart_rate_bpm"] is not None for r in values)
                masks["face"] += bool(video.get("face_detected_frames"))
                masks["posture"] += bool(video.get("pose_detected_frames"))
                statuses[(context.get("video_alignment") or {}).get("quality")] += 1
            profile = context["keyboard_embedding"]["session_embedding"]
            if profile is not None:
                if len(profile) != 128 or not np.isfinite(profile).all() or abs(np.linalg.norm(profile) - 1) > 1e-5:
                    raise ValueError("invalid keyboard profile")
                masks["keyboard"] += 1
            if summary["keyboard_mask"] != (profile is not None):
                raise ValueError("keyboard profile mask mismatch")
            windows = pq.read_table(path.parent / "keyboard_windows.parquet").to_pylist()
            for window in windows:
                if len(window["input_mask"]) != 96 or sum(window["input_mask"]) != window["valid_length"]:
                    raise ValueError("invalid keyboard input mask")
                if window["mask"] and (len(window["embedding"]) != 128 or
                                       abs(np.linalg.norm(window["embedding"]) - 1) > 1e-5):
                    raise ValueError("invalid keyboard window embedding")
            masks["mouse"] += bool(summary["rows"].get("mouse.parquet"))
        except (ValueError, KeyError, OSError, TypeError) as error:
            errors.append({"session_id": sid, "error": str(error)})
    index_path = output / "sessions.parquet"
    index_rows = pq.read_metadata(index_path).num_rows if index_path.exists() else None
    return {"sessions_validated": sum(groups.values()), "groups": dict(groups),
            "rows": dict(rows), "modality_available": dict(masks),
            "video_seconds": total_seconds, "gpu_sessions": dict(devices),
            "video_alignment": dict(statuses), "session_index_rows": index_rows,
            "errors": errors, "passed": not errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "processed")
    parser.add_argument("--expected-sessions", type=int)
    parser.add_argument("--expected-index-rows", type=int)
    args = parser.parse_args()
    result = validate(args.data, args.output)
    for expected, key in ((args.expected_sessions, "sessions_validated"),
                          (args.expected_index_rows, "session_index_rows")):
        if expected is not None and result[key] != expected:
            result["errors"].append({"error": f"Expected {key}={expected}, observed {result[key]}"})
            result["passed"] = False
    write_json(args.output / "validation.json", result)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
