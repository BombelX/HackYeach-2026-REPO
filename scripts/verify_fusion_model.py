"""Verify local fusion execution and recorded evaluation evidence without changing weights.

Run from any directory: .venv/bin/python scripts/verify_fusion_model.py
Optional --database reads a server-owned enrollment database in read-only mode.
Synthetic sensitivity checks are diagnostics, not accuracy or calibration tests.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
from scipy.special import expit
from sklearn.metrics import roc_auc_score
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'research')]
from training.fusion.data import INPUT_DIMS, Pair, pair_tensors, to_torch
from training.fusion.features import CONTEXT_WINDOW_FEATURES, FACE_FEATURES, Profile, SessionWindows
from training.fusion.infer import FusionPredictor


def matching_batch(predictor, profile):
    n = 4
    repeat = lambda value: np.tile(value, (n, 1))
    present = lambda value: np.full(n, value, np.float32)
    sw = SessionWindows('synthetic', profile.participant, 'probe', None,
                        np.arange(n) * 5000, repeat(profile.kb), present(profile.kb_mask),
                        repeat(profile.mouse), present(profile.mouse_mask),
                        repeat(profile.pulse), present(profile.pulse_mask),
                        repeat(profile.face), present(profile.face_mask),
                        np.zeros((n, len(CONTEXT_WINDOW_FEATURES)), np.float32),
                        ctx_mask=np.zeros(n, np.float32))
    arrays = pair_tensors([Pair('synthetic', 'reference', 0, 0, 0, 'diagnostic')],
                          {'synthetic': sw}, {'reference': profile}, predictor.norm)
    return to_torch(arrays, 'cpu')


def outputs(predictor, batch):
    with torch.no_grad():
        result = predictor.model(batch)
    return {name: float(torch.sigmoid(value.mean())) for name, value in result.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT / 'research/training/artifacts/fusion/fusion_model.pt')
    parser.add_argument('--database', type=Path, help='Optional local, server-owned enrollment database; never modified')
    parser.add_argument('--output', type=Path, help='Save aggregate verification results as JSON')
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.manual_seed(0)
    with args.model.open('rb') as source:
        if source.read(80).startswith(b'version https://git-lfs'):
            parser.error('Checkpoint is a Git LFS pointer; download the actual model first.')
    predictor = FusionPredictor(args.model, device='cpu')
    parameter_count = sum(p.numel() for p in predictor.model.parameters())
    checks = {
        'finite_weights': all(bool(torch.isfinite(p).all()) for p in predictor.model.parameters()),
        'positive_finite_normalizer_scales': all(bool(np.isfinite(mean).all() and np.isfinite(std).all() and (std > 0).all()) for mean, std in predictor.norm.stats.values()),
    }
    # Camera-only profile at training feature means; not a real owner recording.
    profile = Profile('synthetic', 'synthetic', np.zeros(128, np.float32), 0,
                      predictor.norm.stats['mouse'][0].copy(), 0,
                      predictor.norm.stats['pulse'][0].copy(), 1,
                      predictor.norm.stats['face'][0].copy(), 1, {})
    batch = matching_batch(predictor, profile)
    baseline = outputs(predictor, batch)
    checks['deterministic_eval'] = baseline == outputs(predictor, batch)
    checks['finite_inference'] = all(np.isfinite(v) for v in baseline.values())
    altered = {k: v.clone() for k, v in batch.items()}
    for name in ('kb', 'mouse', 'ctx', 'net', 'profile_kb'):
        altered[name] = torch.randn_like(altered[name]) * 1000
    mutated = outputs(predictor, altered)
    checks['masked_inputs_do_not_affect_output'] = all(abs(baseline[k] - mutated[k]) < 1e-6 for k in baseline)
    token_fields = [('kb',), ('mouse',), ('pulse',), ('face',), ('ctx', 'net'), ('profile_kb', 'profile_stats')]
    checks['each_masked_token_ignores_its_features'] = True
    for index, fields in enumerate(token_fields):
        masked = {k: v.clone() for k, v in batch.items()}
        masked['mask'][:, index] = 0
        before = outputs(predictor, masked)
        for name in fields:
            masked[name] = torch.randn_like(masked[name]) * 1000
        after = outputs(predictor, masked)
        checks['each_masked_token_ignores_its_features'] &= all(abs(before[k] - after[k]) < 1e-6 for k in before)
    report = {
        'checkpoint_sha256': hashlib.sha256(args.model.read_bytes()).hexdigest(),
        'parameter_count': parameter_count,
        'input_dimensions': INPUT_DIMS,
        'review_threshold': predictor.review_threshold,
        'device_match_scale': predictor.device_scale,
        'execution_checks': checks,
        'synthetic_training_mean_self_reference': baseline,
        'limitations': [
            'Execution checks do not validate owner recognition or manipulation detection.',
            'Synthetic self-reference is not a real held-out recording.',
            'Historical CV predictions are rechecked, not regenerated; source training data is unavailable.',
            'Historical fold models are not the deployed checkpoint; CV is not independent validation of that exact checkpoint.',
            'No independent probability calibration or live user false-alarm measurement is available.',
        ],
    }
    artifact_root = args.model.parent
    scores_path, summary_path = artifact_root / 'cv_scores.json', artifact_root / 'cv_summary.json'
    if scores_path.exists() and summary_path.exists():
        folds, summary = json.loads(scores_path.read_text()), json.loads(summary_path.read_text())
        details = {(fold['seed'], fold['fold']): fold for fold in summary['folds_detail']}
        checks['reported_cv_test_and_validation_people_disjoint'] = all(
            not (set(fold['test_people']) & set(fold['val_people'])) for fold in details.values())
        metrics = {key: [] for key in ('nonowner_auc', 'nonowner_auc_no_context', 'pressure_auc')}
        counts = {}
        for fold in folds:
            pairs = fold['pairs']
            y = np.array([p['nonowner'] for p in pairs])
            valid = np.array([bool(p['pressure_valid']) for p in pairs])
            values = {
                'nonowner_auc': roc_auc_score(y, fold['nonowner']),
                'nonowner_auc_no_context': roc_auc_score(y, fold['nonowner_no_context']),
                'pressure_auc': roc_auc_score(np.array([p['pressure'] for p in pairs])[valid], np.array(fold['pressure'])[valid]),
            }
            for name, value in values.items():
                metrics[name].append(float(value))
            detail = details[(fold['seed'], fold['fold'])]
            for name, value in values.items():
                checks.setdefault('historical_auc_reproduces', True)
                checks['historical_auc_reproduces'] &= abs(float(value) - detail[name]) < 1e-8
            # Recompute review flags independently from saved logits and each fold's threshold.
            nonowner, pressure = expit(fold['nonowner']), expit(fold['pressure'])
            flagged = nonowner + (1 - nonowner) * pressure >= detail['review_threshold']
            seed_counts = counts.setdefault(str(fold['seed']), {})
            for category, selected in {
                'normal_owner': np.array([p['pressure_valid'] == 1 and p['pressure'] == 0 for p in pairs]),
                'scam_owner': np.array([p['kind'] == 'owner_scam' for p in pairs]),
                'impostor': y == 1,
                'natural_intruder': np.array([p['kind'] == 'intruder_victim' for p in pairs]),
            }.items():
                count = seed_counts.setdefault(category, {'total': 0, 'flagged': 0})
                total, alerts = int(selected.sum()), int(flagged[selected].sum())
                count['total'] += total; count['flagged'] += alerts
                checks.setdefault('historical_review_counts_reproduce', True)
                expected = detail['review_counts'][category]
                checks['historical_review_counts_reproduce'] &= (total, alerts) == (expected['total'], expected['flagged'])
        report['historical_cv'] = {
            'fold_evaluations': len(folds), 'people': summary['n_people'], 'sessions': summary['n_sessions'],
            'metrics': {name: {'mean': float(np.mean(values)), 'std': float(np.std(values))} for name, values in metrics.items()},
            'review_counts_by_seed': counts,
            'warning': 'Seeds reuse the same cohort; counts are not independent repeated participants.',
        }
        calibration = summary.get('deployment_calibration', {})
        checks['checkpoint_threshold_matches_summary'] = predictor.review_threshold == calibration.get('threshold')
        report['deployment_threshold_selection'] = {
            'held_out_people': len(calibration.get('held_out_calibration_people', [])),
            'normal_owner_flagged': calibration.get('counts', {}).get('normal_owner', {}).get('flagged'),
            'normal_owner_total': calibration.get('counts', {}).get('normal_owner', {}).get('total'),
            'warning': calibration.get('warning'),
        }
    if args.database:
        import bank24_camera_risk
        with sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True) as connection:
            row = connection.execute('SELECT profile FROM camera_profile_versions WHERE trusted=1 ORDER BY created_at DESC,version DESC LIMIT 1').fetchone()
        if row:
            profile = bank24_camera_risk.load_profile(row[0], ROOT / 'research')
            diagnostic = {'reference_modalities': {name: bool(getattr(profile, name + '_mask')) for name in ('kb', 'mouse', 'pulse', 'face')}, 'device_reference': bool(profile.device), 'synthetic_self_reference': outputs(predictor, matching_batch(predictor, profile))}
            i = FACE_FEATURES.index('browInnerUp_mean')
            edited = copy.deepcopy(profile)
            edited.face[i] = predictor.norm.stats['face'][0][i]
            diagnostic['synthetic_one_feature_at_training_mean'] = outputs(predictor, matching_batch(predictor, edited))
            diagnostic['warning'] = 'Counterfactual only: no saved reference or model weights were modified. Not the actual live recording.'
            report['optional_local_profile_sensitivity'] = diagnostic
    report['verdict'] = 'execution_checks_pass_but_detection_quality_not_verified' if all(checks.values()) else 'execution_or_artifact_check_failed'
    encoded = json.dumps(report, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n')
    print(encoded)
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
