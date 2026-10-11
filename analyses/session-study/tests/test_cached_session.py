import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.finish_cached_session import CachedVisionExtractor, ROOT
from preprocessing.pipeline import artifact_signature


class CachedSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / "cache"
        self.cache.mkdir()
        self.video = Path(self.temporary.name) / "video.webm"
        self.video.write_bytes(b"original video")
        self.code_hash = hashlib.sha256(b"".join(
            p.read_bytes() for p in sorted((ROOT / "preprocessing").glob("*.py")))).hexdigest()
        self.config = {"feature_fps": 5.0, "pulse_batch_size": 8, "max_seconds": None,
                       "implementation_sha256": self.code_hash,
                       "model_artifacts": {name: {"sha256": name + "-historical"}
                                           for name in ("weights", "face_model", "pose_model")}}
        self.summary = {"config": {k: self.config[k] for k in
                                   ("feature_fps", "pulse_batch_size", "max_seconds")},
                        "source_video_sha256": artifact_signature(self.video)["sha256"],
                        "rppg_weights_sha256": "weights-historical",
                        "face_model_sha256": "face_model-historical",
                        "pose_model_sha256": "pose_model-historical"}
        for name in ("video_frames.jsonl", "pulse.jsonl", "pulse_windows.jsonl"):
            (self.cache / name).write_text('{"real_observation":1}\n')
        self.write_validation()

    def write_validation(self):
        (self.cache / "video_summary.json").write_text(json.dumps(self.summary))
        validation = {"status": "PASS", "errors": [],
                      "preprocessing_implementation_sha256": self.code_hash,
                      "cache_artifacts_sha256": {name: artifact_signature(self.cache / name)["sha256"]
                                                for name in ("video_frames.jsonl", "pulse.jsonl",
                                                             "pulse_windows.jsonl", "video_summary.json")}}
        (self.cache / "parallel_validation.json").write_text(json.dumps(validation))

    def test_matching_cache_copies_validated_artifacts(self):
        extractor = CachedVisionExtractor(self.cache, self.config)
        output = Path(self.temporary.name) / "output"
        output.mkdir()
        summary = extractor.extract(self.video, output)
        self.assertEqual(summary["source_video_sha256"], self.summary["source_video_sha256"])
        self.assertEqual((output / "pulse.jsonl").read_bytes(), (self.cache / "pulse.jsonl").read_bytes())
        self.assertTrue((output / "parallel_validation.json").is_file())

    def test_changed_cache_is_rejected_even_with_old_pass_report(self):
        (self.cache / "pulse.jsonl").write_text('{"edited":true}\n')
        with self.assertRaisesRegex(ValueError, "validated content"):
            CachedVisionExtractor(self.cache, self.config)

    def test_changed_raw_video_is_rejected(self):
        extractor = CachedVisionExtractor(self.cache, self.config)
        self.video.write_bytes(b"other video")
        with self.assertRaisesRegex(ValueError, "source video differs"):
            extractor.extract(self.video, self.cache)

    def test_saved_landmark_model_hash_is_required(self):
        self.summary["face_model_sha256"] = "other historical model"
        self.write_validation()
        with self.assertRaisesRegex(ValueError, "landmark model mismatch"):
            CachedVisionExtractor(self.cache, self.config)

    def test_template_with_other_code_is_rejected(self):
        self.config["implementation_sha256"] = "older implementation"
        with self.assertRaisesRegex(ValueError, "preprocessing code differs"):
            CachedVisionExtractor(self.cache, self.config)


if __name__ == "__main__":
    unittest.main()
