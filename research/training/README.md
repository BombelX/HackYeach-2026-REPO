# LightGBM experiment

This directory contains a session-level LightGBM training pipeline for the HackYeah dataset.

## What it trains

- binary classification: `scam`/`intruder` vs all other conditions
- regression: `stress` (1..7) prediction

## Run

```bash
PYTHONPATH=research .venv/bin/python research/training/lightgbm_experiment.py --gpu-device 0
```

To sweep all visible GPUs:

```bash
PYTHONPATH=research .venv/bin/python research/training/lightgbm_experiment.py
```

## Artifacts

All results and trained models are saved under `research/training/artifacts/` (one canonical copy).

## Multimodal fusion

The final model combines keyboard, mouse, pulse, face, context and owner profile.
See [fusion/README.md](fusion/README.md) for architecture, results and network-model
integration. Old XGBoost models under `artifacts/xgboost*/` were trained on leaking
survey/condition features and must not be used.

The GUIDÆTA mouse CatBoost/XGBoost benchmark runs as
`python -m training.mouse_boost_benchmark` with `research/` on `PYTHONPATH`.
Parameters are selected on validation people and evaluated on disjoint test people.
The fusion README documents results and integration limitations.
