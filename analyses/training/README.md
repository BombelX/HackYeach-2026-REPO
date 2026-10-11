# LightGBM experiment

This directory contains a session-level LightGBM training pipeline for the HackYeah dataset.

## What it trains

- binary classification: `scam`/`intruder` vs all other conditions
- regression: `stress` (1..7) prediction

## Run

```bash
source /venv/main/bin/activate
cd /workspace/hackaton/HackYeach-2026-REPO
python training/lightgbm_experiment.py --gpu-device 0
```

To sweep all visible GPUs:

```bash
python training/lightgbm_experiment.py
```

## Artifacts

All results and trained models are saved under `training/artifacts/`.

## Fuzja multimodalna

Końcowy model łączący klawiaturę, mysz, tętno, twarz, kontekst i profil: `training/fusion/` (opis, wyniki, sposób podpięcia modelu sieci w `training/fusion/README.md`). Stare modele XGBoost z `training/artifacts/xgboost*/` były uczone na przeciekających cechach (ankieta, warunek) — nie używać.

Benchmark CatBoost vs XGBoost dla weryfikacji myszy GUIDÆTA:
`/venv/main/bin/python -m training.mouse_boost_benchmark`. Wybór parametrów odbywa się
na osobach walidacyjnych, ocena na rozłącznych osobach testowych.
Wyniki i ograniczenia integracji opisuje `training/fusion/README.md`.
