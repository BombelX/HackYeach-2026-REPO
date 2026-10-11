"""Adapt consented bank metadata to the fusion model's processed input format."""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

KEYBOARD_MODEL = Path(__file__).resolve().parents[1] / 'models/keystroke/long-run/keystroke_long_epoch_59.pt'
FIELDS = {'username': 'client_id', 'recipient': 'payee', 'number': 'nrb'}


@lru_cache(maxsize=1)
def keyboard_model():
    import torch
    from training.train_keystroke import KeystrokeConformer
    with KEYBOARD_MODEL.open('rb') as source:
        if source.read(80).startswith(b'version https://git-lfs'):
            raise ValueError('Download models/keystroke/long-run/keystroke_long_epoch_59.pt with Git LFS.')
    model = KeystrokeConformer()
    model.load_state_dict(torch.load(KEYBOARD_MODEL, map_location='cpu', weights_only=True))
    return model.eval()


def encode_keyboard(keys, features):
    """Key identifiers are used transiently; only the embedding is saved."""
    import torch
    length = len(keys)
    padded_keys = np.zeros((1, 96), np.int64)
    padded_features = np.zeros((1, 96, 8), np.float32)
    padded_keys[0, :length] = keys
    padded_features[0, :length] = np.asarray(features, dtype=np.float16).astype(np.float32)
    mask = torch.arange(96)[None] < length
    with torch.no_grad():
        vector = keyboard_model()(torch.from_numpy(padded_keys), torch.from_numpy(padded_features), mask)[0]
        return torch.nn.functional.normalize(vector, dim=0).tolist()


def write_inputs(trace, directory, start_ms, end_ms):
    events = trace.get('telemetry') or []
    origin = trace.get('started_epoch_ms')
    if origin is None:
        return
    mouse, markers, network, keyboard = [], [], [], []
    field_ids = {}
    for event in events:
        t = event['page_anchor_ms'] + event['time_ms'] - origin
        kind = event['type']
        # Environment applies to the whole session, including later probe slices.
        if kind != 'environment' and not (start_ms <= t and (end_ms is None or t < end_ms)):
            continue
        if kind == 'keyboard_embedding' and t - event['duration_ms'] < start_ms:
            continue  # Never reuse typing from before this enrollment/probe slice.
        t = max(0, t - start_ms)
        field = FIELDS.get(event['field'], event['field'])
        field_id = field_ids.setdefault(field, len(field_ids))
        if kind in ('pointer', 'pointerdown', 'pointerup', 'click', 'wheel'):
            mouse.append(dict(t_session_ms=t, x=event.get('x', 0) * event.get('width', 1),
                              y=event.get('y', 0) * event.get('height', 1),
                              event_type_id={'pointer': 0, 'pointerdown': 1, 'pointerup': 2, 'click': 3, 'wheel': 4}[kind],
                              pointer_type_id=0, delta_y=event.get('delta_y', 0), field_id=field_id, mask=True))
        elif kind == 'keyboard_embedding':
            keyboard.append(dict(start_t_session_ms=max(0, t - event['duration_ms']), end_t_session_ms=t,
                                 valid_length=event['length'], embedding=event['embedding'], field_id=field_id, mask=True))
        elif kind in ('environment', 'ping', 'server_request'):
            network.append(dict(type=kind, t_session_ms=t, payload_json=json.dumps({'env': event.get('env', {}), 'status': event.get('status', 200)}),
                                rtt_ms=event.get('duration_ms') if kind == 'ping' else None,
                                duration_ms=event.get('duration_ms') if kind == 'server_request' else None))
        else:
            marker = {'focus': 'field_focus'}.get(kind, kind)
            markers.append(dict(type=marker, t_session_ms=t, payload_json=json.dumps({'field': field, 'hidden': kind == 'hidden'})))
    for name, rows in [('mouse', mouse), ('markers', markers), ('network', network), ('keyboard_windows', keyboard)]:
        if rows:
            pd.DataFrame(rows).sort_values('start_t_session_ms' if name == 'keyboard_windows' else 't_session_ms').to_parquet(directory / f'{name}.parquet')
    (directory / 'context.json').write_text(json.dumps({'keyboard_fields': field_ids, 'mouse_fields': field_ids}))
