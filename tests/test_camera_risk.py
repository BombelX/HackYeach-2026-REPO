import tempfile
import unittest
import pickle
from pathlib import Path

import pandas as pd

import bank24_camera_risk as camera_risk
from webrtc_server import TRACE_BLENDSHAPES, posture_metrics

FUSION_REPO = Path(__file__).resolve().parents[1] / 'analyses'


def trace(seconds, bpm=72.0):
    samples = []
    for i in range(int(seconds * 30)):
        sample = dict(t=i * 1000 / 30, width=640, bpm=bpm, concentration=0.6, face_crop_valid=True)
        if i % 3 == 0:
            sample.update(blendshapes=[0.2] * len(TRACE_BLENDSHAPES), face_bbox=[200, 100, 400, 350],
                          posture=dict(head_shoulder_ratio=1.2, head_tilt_degrees=2.0, shoulder_tilt_degrees=1.0,
                                       shoulder_width_normalized=0.4))
        samples.append(sample)
    return dict(blendshapes=list(TRACE_BLENDSHAPES), samples=samples)


class CameraRiskTest(unittest.TestCase):
    def test_write_session_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            camera_risk.write_session(trace(20), Path(tmp), start_ms=10_000)
            pulse = pd.read_parquet(Path(tmp) / 'pulse.parquet')
            timeline = pd.read_parquet(Path(tmp) / 'timeline.parquet')
            frames = pd.read_parquet(Path(tmp) / 'frames.parquet')
        self.assertEqual(pulse['t_session_ms'].min(), 0)
        self.assertTrue(pulse['heart_rate_status'].eq('estimate').all())
        self.assertEqual(len(timeline), len(frames))
        self.assertIn('face_jawOpen', timeline)
        self.assertIn('posture_head_tilt_degrees', timeline)

    def test_posture_metrics(self):
        pose = [dict(x=0.5, y=0.5, visibility=1.0)] * 13
        pose = list(pose)
        pose[7], pose[8] = dict(x=0.45, y=0.3, visibility=1), dict(x=0.55, y=0.3, visibility=1)
        pose[11], pose[12] = dict(x=0.35, y=0.6, visibility=1), dict(x=0.65, y=0.6, visibility=1)
        metrics = posture_metrics(pose, 640, 480)
        self.assertAlmostEqual(metrics['shoulder_tilt_degrees'], 0)
        self.assertAlmostEqual(metrics['shoulder_width_normalized'], 0.3)
        pose[7] = dict(x=0.45, y=0.3, visibility=0.1)
        self.assertIsNone(posture_metrics(pose, 640, 480))

    def test_risk_mapping(self):
        risk = camera_risk.risk_from_camera(dict(p_not_owner=0.4, p_pressure=0.75, review_required=True,
                                                 review_score=0.5, review_threshold=0.13, probe_seconds=30,
                                                 profile_enrolled_now=False))
        self.assertEqual((risk['account_takeover_risk'], risk['coercion_risk']), (40, 75))
        self.assertEqual(risk['action'], 'additional_verification')
        self.assertIn('independent_recipient_check', risk['recommended_interventions'])

    @unittest.skipUnless((FUSION_REPO / 'training/inference_xgb_suspicious.py').exists(), 'fusion repo missing')
    def test_explicit_enrolment_then_score_without_writing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(camera_risk.CameraRiskUnavailable):
                camera_risk.build_enrollment_sample(trace(6), 'p', FUSION_REPO)
            with self.assertRaises(camera_risk.CameraRiskUnavailable):
                camera_risk.build_enrollment_sample(trace(45), 'p', FUSION_REPO, start_ms=10_000)
            sparse_face = trace(60)
            for frame in sparse_face['samples']:
                if frame['t'] < 45_000:
                    frame.pop('blendshapes', None)
            with self.assertRaises(camera_risk.CameraRiskUnavailable):
                camera_risk.build_enrollment_sample(sparse_face, 'p', FUSION_REPO)
            sample = camera_risk.build_enrollment_sample(trace(60), 'p', FUSION_REPO)
            later_sample = camera_risk.build_enrollment_sample(trace(60), 'p', FUSION_REPO, start_ms=10_000)
            self.assertEqual(later_sample.participant, 'p')
            loaded = camera_risk.load_profile(pickle.dumps(sample), FUSION_REPO)
            self.assertEqual(loaded.participant, 'p')
            profile = camera_risk.combine_samples([sample, sample, sample], 'p')
            scored = camera_risk.assess_camera(trace(40), 'p', FUSION_REPO, profile)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertFalse(scored['profile_enrolled_now'])
        self.assertTrue(0 <= scored['review_score'] <= 1)


if __name__ == '__main__':
    unittest.main()
