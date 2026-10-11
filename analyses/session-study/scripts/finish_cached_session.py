#!/usr/bin/env python3
"""Commit a verified parallel vision cache through the normal session pipeline."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from preprocessing.pipeline import artifact_signature, process_session
from preprocessing.sessions import inventory
from preprocessing.tables import write_json


class CachedVisionExtractor:
    def __init__(self, cache: Path, config: dict):
        self.cache = cache
        self.summary = json.loads((cache / "video_summary.json").read_text())
        self.validation = json.loads((cache / "parallel_validation.json").read_text())
        if self.validation["status"] != "PASS" or self.validation["errors"]:
            raise ValueError("Parallel cache did not pass coverage validation")
        for name in ("video_frames.jsonl", "pulse.jsonl", "pulse_windows.jsonl", "video_summary.json"):
            expected = self.validation.get("cache_artifacts_sha256", {}).get(name)
            if not expected or artifact_signature(cache / name)["sha256"] != expected:
                raise ValueError("Cache file differs from validated content: " + name)
        current_code = hashlib.sha256(b"".join(
            p.read_bytes() for p in sorted((ROOT / "preprocessing").glob("*.py")))).hexdigest()
        if (self.validation.get("preprocessing_implementation_sha256") != current_code or
                config["implementation_sha256"] != current_code):
            raise ValueError("Cache/template preprocessing code differs from current code")
        if not self.summary.get("source_video_sha256"):
            raise ValueError("Cache must include a SHA256 of the original joined video")
        requested = self.summary["config"]
        for key in ("feature_fps", "pulse_batch_size", "max_seconds"):
            if requested[key] != config[key]:
                raise ValueError("Cache configuration mismatch: " + key)
        if self.summary["rppg_weights_sha256"] != config["model_artifacts"]["weights"]["sha256"]:
            raise ValueError("Cache PhysNet weights mismatch")
        for key in ("face_model", "pose_model"):
            if self.summary.get(key + "_sha256") != config["model_artifacts"][key]["sha256"]:
                raise ValueError("Cache landmark model mismatch: " + key)

    def extract(self, video: Path, output: Path) -> dict:
        if artifact_signature(video)["sha256"] != self.summary["source_video_sha256"]:
            raise ValueError("Cache source video differs from current session chunks")
        for name in ("video_frames.jsonl", "pulse.jsonl", "pulse_windows.jsonl",
                     "parallel_validation.json"):
            shutil.copy2(self.cache / name, output / name)
        summary = dict(self.summary)
        summary["parallel_cache_validation"] = self.validation
        write_json(output / "video_summary.json", summary)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--template-summary", type=Path, required=True)
    args = parser.parse_args()
    template = json.loads(args.template_summary.read_text())
    config = template["config"]
    config["force"] = False
    for name in ("keyboard_checkpoint", "weights", "face_model", "pose_model"):
        if artifact_signature(config[name])["sha256"] != config["model_artifacts"][name]["sha256"]:
            raise ValueError("Template model changed on disk: " + name)
    output = Path(config["output"])
    with (output / ".pipeline.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = next(r for r in inventory(config["data"]) if r.session_id == args.session)
        if record.status not in {"ready", "incomplete_session"}:
            raise ValueError("Session is not eligible: " + record.status)
        from preprocessing.model_keyboard import KeyboardEmbedder
        import torch
        torch.set_num_threads(config["cpu_threads"])
        embedder = KeyboardEmbedder(config["keyboard_checkpoint"], device="cpu")
        extractor = CachedVisionExtractor(args.cache, config)
        target = output / "sessions" / record.group / record.session_id
        print("Committing cached extraction for " + record.session_id, flush=True)
        result = process_session(record, target, config, extractor, embedder)
        write_json(output / ("cached_commit_" + record.session_id + ".json"), result)
        print(json.dumps({k: v for k, v in result.items() if k != "video"}), flush=True)


if __name__ == "__main__":
    main()
