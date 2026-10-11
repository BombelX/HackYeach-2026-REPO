from pathlib import Path

import numpy as np

from training.fusion_session_model import SessionFusionDataset, build_session_records, make_person_split


def test_real_session_records_and_token_shapes():
    records = build_session_records(Path(__file__).resolve().parents[1] / 'data' / 'processed')
    assert len(records) > 0
    split = make_person_split(records)
    assert split['train']
    assert split['val']
    assert split['test']

    ds = SessionFusionDataset(records[:2])
    sample = ds[0]
    assert sample['tokens'].shape == (6, 128)
    assert sample['mask'].shape == (6,)
    assert sample['suspicious'].shape == ()
    assert sample['pressure'].shape == ()
    assert sample['owner'].shape == ()
    assert np.isfinite(sample['tokens']).all()
