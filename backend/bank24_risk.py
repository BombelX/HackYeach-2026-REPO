"""Transparent, unvalidated behavioral features for the Bank24 study demo.

This module extracts metadata-only features from consented telemetry and
compares them with operator-designated calm-owner sessions. Scores are
heuristic indicators, not calibrated probabilities or fraud determinations.
"""
import json
import math
import statistics
import time


MODEL_VERSION = 'robust-baseline-v1'
MIN_OBSERVATIONS = 3
MIN_EVENTS = 8
MIN_KEY_PRESSES = 5

FEATURE_LABELS = {
    'active_duration_s': 'czas aktywności formularza',
    'key_press_count': 'liczba naciśnięć klawiszy',
    'input_rate_per_min': 'tempo zmian pól',
    'correction_rate': 'udział korekt',
    'focus_changes': 'liczba zmian pola',
    'pointer_distance': 'łączny dystans wskaźnika',
    'pointer_pause_ratio': 'udział krótkich postojów wskaźnika',
    'median_key_dwell_ms': 'mediana czasu przytrzymania klawisza',
    'median_inter_key_ms': 'mediana odstępu między klawiszami',
    'fields_touched': 'liczba użytych pól',
}

# Lower bounds keep a zero MAD from making a tiny difference look enormous.
SCALE_FLOORS = {
    'active_duration_s': 2.0,
    'key_press_count': 3.0,
    'input_rate_per_min': 1.0,
    'correction_rate': 0.08,
    'focus_changes': 1.0,
    'pointer_distance': 0.04,
    'pointer_pause_ratio': 0.08,
    'median_key_dwell_ms': 20.0,
    'median_inter_key_ms': 80.0,
    'fields_touched': 1.0,
}


def extract_features(db, study_session_id, stage):
    """Return aggregate timing/interaction metadata for one session stage."""
    rows = db.execute(
        'SELECT page,event FROM telemetry WHERE study_session=? ORDER BY page,sequence',
        (study_session_id,),
    ).fetchall()
    events = []
    for row in rows:
        try:
            event = json.loads(row['event'])
        except (TypeError, json.JSONDecodeError):
            continue
        if event.get('stage') == stage:
            events.append((row['page'], event))

    by_page = {}
    for page, event in events:
        anchor = event.get('page_anchor_ms')
        relative = event.get('time_ms')
        if (isinstance(anchor, (int, float)) and math.isfinite(anchor) and
                isinstance(relative, (int, float)) and math.isfinite(relative)):
            timestamp = anchor + relative
        else:
            timestamp = event.get('received_at', 0) * 1000
        by_page.setdefault(page, []).append((timestamp, event))

    active_ms = 0.0
    key_times = []
    dwell = []
    pointer_distances = []
    pointer_steps = 0
    pointer_pauses = 0
    valid_pointer_count = 0
    for page, points in by_page.items():
        points.sort(key=lambda pair: pair[0])
        if points:
            active_ms += max(0.0, points[-1][0] - points[0][0])
        page_key_times = []
        last_pointer = None
        for timestamp, event in points:
            kind = event.get('type')
            if kind == 'key_press':
                page_key_times.append(timestamp)
            elif kind == 'key_dwell':
                value = event.get('duration_ms')
                if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 5000:
                    dwell.append(float(value))
            elif kind == 'pointer':
                x, y = event.get('x'), event.get('y')
                if (isinstance(x, (int, float)) and isinstance(y, (int, float)) and
                        math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
                    current = (float(x), float(y))
                    valid_pointer_count += 1
                    if last_pointer is not None:
                        distance = math.dist(last_pointer, current)
                        pointer_distances.append(distance)
                        pointer_steps += 1
                        if distance <= 0.01:
                            pointer_pauses += 1
                    last_pointer = current
        key_times.extend((page, timestamp) for timestamp in page_key_times)

    key_times.sort(key=lambda item: (item[0], item[1]))
    inter_key = []
    previous_page = None
    previous_time = None
    for page, timestamp in key_times:
        if page == previous_page and previous_time is not None:
            gap = timestamp - previous_time
            if 0 <= gap <= 10000:
                inter_key.append(gap)
        previous_page, previous_time = page, timestamp

    key_press_count = sum(event.get('type') == 'key_press' for _, event in events)
    input_count = sum(event.get('type') == 'input' for _, event in events)
    correction_count = sum(event.get('type') == 'correction' for _, event in events)
    focus_changes = sum(event.get('type') == 'focus' for _, event in events)
    pointer_event_count = valid_pointer_count
    fields_touched = len({
        event.get('field') for _, event in events
        if event.get('type') in ('input', 'focus', 'correction', 'key_press')
        and event.get('field') not in (None, 'none')
    })
    active_duration_s = min(7200.0, active_ms / 1000.0)
    features = {
        'active_duration_s': active_duration_s,
        'key_press_count': float(key_press_count),
        'input_rate_per_min': input_count / max(active_duration_s, 1.0) * 60.0,
        'correction_rate': correction_count / max(key_press_count, 1),
        'focus_changes': float(focus_changes),
        'pointer_distance': sum(pointer_distances) if pointer_steps else None,
        'pointer_pause_ratio': pointer_pauses / pointer_steps if pointer_steps else None,
        'median_key_dwell_ms': statistics.median(dwell) if dwell else None,
        'median_inter_key_ms': statistics.median(inter_key) if inter_key else None,
        'fields_touched': float(fields_touched),
    }
    ready = len(events) >= MIN_EVENTS and key_press_count >= MIN_KEY_PRESSES and active_duration_s >= 1.0
    missing = []
    if len(events) < MIN_EVENTS:
        missing.append('Za mało zdarzeń w tym etapie.')
    if key_press_count < MIN_KEY_PRESSES:
        missing.append('Za mało metadanych o naciśnięciach klawiszy.')
    if active_duration_s < 1.0:
        missing.append('Brak wystarczającego zakresu czasu.')
    return {
        'stage': stage,
        'event_count': len(events),
        'key_press_count': key_press_count,
        'modalities': {
            'keyboard': key_press_count > 0,
            'pointer': pointer_event_count > 0,
            'form': input_count + focus_changes + correction_count > 0,
        },
        'features': features,
        'ready': ready,
        'missing_reasons': missing,
    }


def rebuild_owner_profile(db, bank_participant, stage):
    """Rebuild a versioned profile from completed operator-assigned calm sessions."""
    sessions = db.execute(
        '''SELECT ss.id FROM study_sessions ss
           JOIN study_participants sp ON sp.id=ss.study_participant
           WHERE ss.bank_participant=? AND ss.scenario='calm_owner'
             AND ss.status='completed' AND ss.telemetry_allowed=1 AND sp.withdrawn=0 AND sp.role='owner'
           ORDER BY ss.ended_at,ss.id''',
        (bank_participant,),
    ).fetchall()
    observations = []
    modalities = set()
    for row in sessions:
        extracted = extract_features(db, row['id'], stage)
        if extracted['ready']:
            observations.append(extracted['features'])
            modalities.update(name for name, active in extracted['modalities'].items() if active)

    feature_stats = {}
    all_features = set().union(*(item.keys() for item in observations)) if observations else set()
    for name in all_features:
        values = [item[name] for item in observations if item.get(name) is not None]
        if values:
            center = statistics.median(values)
            mad = statistics.median(abs(value - center) for value in values)
            feature_stats[name] = {'median': center, 'mad': mad}

    ready = len(observations) >= MIN_OBSERVATIONS
    db.execute(
        '''INSERT INTO owner_profiles(bank_participant,stage,version,observations,features,modalities,ready,updated_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(bank_participant,stage) DO UPDATE SET
             version=excluded.version,observations=excluded.observations,
             features=excluded.features,modalities=excluded.modalities,
             ready=excluded.ready,updated_at=excluded.updated_at''',
        (bank_participant, stage, MODEL_VERSION, len(observations), json.dumps(feature_stats), json.dumps(sorted(modalities)), int(ready), time.time()),
    )
    return {
        'stage': stage,
        'version': MODEL_VERSION,
        'observations': len(observations),
        'modalities': sorted(modalities),
        'ready': ready,
        'features': feature_stats,
    }


def compare_with_profile(current, profile):
    """Score robust deviations; score range is an uncalibrated 0..100 indicator."""
    if not current['ready'] or not profile or not profile['ready']:
        return None, [], 'insufficient_data'
    baseline = json.loads(profile['features']) if isinstance(profile['features'], str) else profile['features']
    deviations = []
    for name, values in baseline.items():
        observed = current['features'].get(name)
        if observed is None:
            continue
        center, mad = values.get('median'), values.get('mad')
        if center is None or mad is None:
            continue
        scale = max(1.4826 * float(mad), SCALE_FLOORS.get(name, 1.0))
        z = abs(float(observed) - float(center)) / scale
        points = min(100.0, z * 20.0)
        deviations.append((name, points, z, float(observed), float(center)))
    if len(deviations) < 3:
        return None, [], 'insufficient_data'
    mean_score = sum(item[1] for item in deviations) / len(deviations)
    max_score = max(item[1] for item in deviations)
    score = round(0.65 * mean_score + 0.35 * max_score)
    explanations = []
    for name, points, z, observed, center in sorted(deviations, key=lambda item: item[2], reverse=True):
        if z >= 2.0:
            direction = 'więcej' if observed > center else 'mniej'
            explanations.append({
                'feature': name,
                'label': FEATURE_LABELS.get(name, name),
                'observed': round(observed, 3),
                'baseline_median': round(center, 3),
                'deviation_mad': round(z, 2),
                'message': f'{FEATURE_LABELS.get(name, name)}: {direction} niż typowo w profilu właściciela.',
            })
        if len(explanations) == 4:
            break
    return score, explanations, 'limited'
