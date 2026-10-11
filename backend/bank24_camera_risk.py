"""Camera-based transfer risk using the fusion model behind training/inference_xgb_suspicious.py.

The camera worker records per-frame pulse, face blendshapes, posture and face boxes. This module
writes them in the processed-session layout read by ``training.fusion.features`` and scores them
with ``predict_suspicious``. Only camera modalities are available here: keyboard, mouse, context
and device inputs are absent and therefore masked, so the result is an experimental review signal,
not a fraud probability.

Owner profiles are built only through the explicit enrolment endpoint. Each sample comes from a
separate verified bank session. Risk assessment receives an already saved profile and never writes one.
"""
from __future__ import annotations

import pickle
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

POSTURE = ('head_shoulder_ratio', 'head_tilt_degrees', 'shoulder_tilt_degrees', 'shoulder_width_normalized')
PROBE_SECONDS = 120.0
MODEL_LABEL = 'fusion-transformer-camera (inference_xgb_suspicious)'

class CameraRiskUnavailable(Exception):
    """Not enough camera data (or model missing) to score."""


def _import_model(fusion_repo: Path):
    root = str(Path(fusion_repo).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    from training import inference_xgb_suspicious as inference  # noqa: PLC0415
    from training.fusion.features import WINDOW_MS, build_profile, build_session_windows  # noqa: PLC0415
    return inference, build_session_windows, build_profile, WINDOW_MS


def load_profile(blob: bytes, fusion_repo: Path):
    """Load a server-owned profile after registering the model module for fresh processes."""
    _import_model(fusion_repo)
    return pickle.loads(blob)


def write_session(trace: dict[str, Any], directory: Path, start_ms: float = 0.0, end_ms: float | None = None) -> int:
    """Write samples with start_ms <= t < end_ms; times are rebased so the slice starts at 0."""
    names = trace.get('blendshapes') or []
    samples = [s for s in trace.get('samples') or []
               if s.get('t') is not None and s['t'] >= start_ms and (end_ms is None or s['t'] < end_ms)]
    directory.mkdir(parents=True, exist_ok=True)
    pulse, timeline, frames = [], [], []
    for s in samples:
        t = float(s['t']) - start_ms
        bpm = s.get('bpm')
        pulse.append(dict(t_session_ms=t, heart_rate_bpm=bpm,
                          heart_rate_status='estimate' if bpm is not None else 'unavailable',
                          spectral_concentration=s.get('concentration'),
                          face_crop_valid=bool(s.get('face_crop_valid'))))
        if 'blendshapes' not in s:
            continue  # landmarks were not run on this frame
        row = dict(t_session_ms=t)
        values = s.get('blendshapes')
        for i, name in enumerate(names):
            value = values[i] if values and i < len(values) else None
            row[f'face_{name}'] = value
            row[f'face_{name}_valid'] = value is not None
        posture = s.get('posture') or {}
        for name in POSTURE:
            row[f'posture_{name}'] = posture.get(name)
            row[f'posture_{name}_valid'] = name in posture
        timeline.append(row)
        box = s.get('face_bbox')
        frames.append(dict(t_session_ms=t, face_detected=box is not None, face_bbox_pixels=box,
                           width=s.get('width')))
    pd.DataFrame(pulse).to_parquet(directory / 'pulse.parquet')
    pd.DataFrame(timeline).to_parquet(directory / 'timeline.parquet')
    pd.DataFrame(frames, columns=['t_session_ms', 'face_detected', 'face_bbox_pixels', 'width']).to_parquet(
        directory / 'frames.parquet')
    return len(samples)


def build_enrollment_sample(trace: dict[str, Any], participant: str, fusion_repo: Path,
                            start_ms: float = 0.0):
    """Extract one calm sample; the caller decides if the session is trusted and stores it."""
    _, build_session_windows, build_profile, window_ms = _import_model(fusion_repo)
    samples = [sample for sample in trace.get('samples') or []
               if sample.get('t') is not None and float(sample['t']) >= start_ms]
    if not samples:
        raise CameraRiskUnavailable('Kamera nie przesłała jeszcze danych do analizy.')
    if float(samples[-1]['t']) - max(start_ms, float(samples[0]['t'])) < 40_000:
        raise CameraRiskUnavailable('Do zapisu próbki potrzeba co najmniej 40 s spokojnego nagrania z widoczną twarzą.')
    with tempfile.TemporaryDirectory(prefix='bank24-camera-') as tmp:
        tmp = Path(tmp)
        write_session(trace, tmp / 'enrol', start_ms)
        windows = build_session_windows(tmp / 'enrol', dict(session_id='enrol', participant_code=participant,
                                                            condition='calm_1'))
        if windows is None or len(windows.starts) == 0:
            raise CameraRiskUnavailable('Za mało danych z widoczną twarzą do zapisania próbki profilu.')
        visible_windows = int(np.count_nonzero(windows.face_mask))
        if visible_windows < 3 or visible_windows * 2 < len(windows.starts):
            raise CameraRiskUnavailable('Twarz musi być widoczna w większości pomiaru, przez co najmniej trzy okna analizy.')
        # Training split a calm session into enrolment/probe halves. Here the probe is a future
        # login, so the whole explicitly started calm recording can contribute to the profile.
        windows.split_ms = float(windows.starts[-1] + window_ms)
        profile = build_profile(windows)
        if profile is None or profile.face_mask <= 0:
            raise CameraRiskUnavailable('Za mało danych z widoczną twarzą do zapisania próbki profilu.')
        return profile


def combine_samples(samples: list, participant: str):
    """Mean available camera features across trusted recordings; missing modalities stay masked."""
    if not samples or any(sample.participant != participant for sample in samples):
        raise ValueError('Próbki muszą należeć do jednego właściciela.')
    from training.fusion.features import Profile  # imported after _import_model has set the path

    def mean(name):
        mask_name = name + '_mask'
        available = [getattr(sample, name) for sample in samples if getattr(sample, mask_name) > 0]
        reference = getattr(samples[0], name)
        return (np.mean(available, axis=0).astype(np.float32), 1.0) if available else (np.zeros_like(reference), 0.0)

    kb, kb_mask = mean('kb')
    mouse, mouse_mask = mean('mouse')
    pulse, pulse_mask = mean('pulse')
    face, face_mask = mean('face')
    if kb_mask:
        kb /= max(float(np.linalg.norm(kb)), 1e-8)
    return Profile(participant, 'trusted-enrolment', kb, kb_mask, mouse, mouse_mask,
                   pulse, pulse_mask, face, face_mask, samples[-1].device)


def assess_camera(trace: dict[str, Any], participant: str, fusion_repo: Path, profile,
                  start_ms: float | None = None) -> dict[str, Any]:
    """Score against an existing profile without changing it."""
    inference, _, _, window_ms = _import_model(fusion_repo)
    samples = trace.get('samples') or []
    if not samples:
        raise CameraRiskUnavailable('Kamera nie przesłała jeszcze danych do analizy.')
    if profile.participant != participant:
        raise CameraRiskUnavailable('Profil nie należy do tego konta.')
    duration = float(samples[-1]['t'])
    probe_start = max(start_ms or 0.0, duration - PROBE_SECONDS * 1000)
    with tempfile.TemporaryDirectory(prefix='bank24-camera-') as tmp:
        tmp = Path(tmp)
        if write_session(trace, tmp / 'probe', probe_start) == 0 or duration - probe_start < window_ms / 2:
            raise CameraRiskUnavailable('Za mało nowych danych z kamery do oceny przelewu.')
        try:
            result = inference.predict_suspicious(tmp / 'probe', profile)
        except ValueError as exc:
            raise CameraRiskUnavailable('Za mało danych z kamery do oceny przelewu.') from exc
    result.update(profile_enrolled_now=False, probe_seconds=round((duration - probe_start) / 1000, 1),
                  profile_session=profile.session_id)
    result.pop('model_path', None)
    result['session_id'] = 'live'
    result['profile'] = participant
    return result


def risk_from_camera(result: dict[str, Any], model_version: str = MODEL_LABEL) -> dict[str, Any]:
    """Map the model output onto the Bank24 risk contract shown in the transfer review."""
    import time

    nonowner = round(100 * result['p_not_owner'])
    pressure = round(100 * result['p_pressure'])
    review = bool(result['review_required'])
    interventions = []
    if review:
        interventions.append('additional_transaction_verification')
    if pressure >= 70:
        interventions.append('independent_recipient_check')
    reasons = [
        f"Model fuzji (kamera: tętno, mimika, postawa) porównał ostatnie {result['probe_seconds']} s "
        f"z profilem właściciela.",
        f"Wynik przeglądu {result['review_score']:.2f} przy progu {result['review_threshold']:.2f}"
        + (' — zalecana dodatkowa weryfikacja.' if review else ' — poniżej progu.'),
    ]
    reasons.append('Brak danych klawiatury, myszy i urządzenia — te modalności są pominięte.')
    reasons.append('Wskaźniki są eksperymentalne i niezwalidowane; nie są prawdopodobieństwem oszustwa.')
    return dict(
        account_takeover_risk=nonowner, coercion_risk=pressure, assessment_status='limited', quality='limited',
        available_signals=['camera_pulse', 'camera_face'], missing_reasons=[],
        action='additional_verification' if review else 'standard_confirmation',
        recommended_interventions=interventions, reasons=reasons, explanations=[],
        model_version=model_version, validated=False, assessed_at=time.time(),
        camera_model={k: result[k] for k in ('review_score', 'review_threshold', 'review_required',
                                             'p_not_owner', 'p_pressure', 'probe_seconds',
                                             'profile_enrolled_now')},
    )
