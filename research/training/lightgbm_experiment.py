#!/usr/bin/env python3
"""LightGBM experiment for scam/intruder stress analysis.

The script builds a session-level dataset from the processed pipeline output for:
- binary classification: scam/intruder vs all other conditions
- regression: predicted stress score from 1..7

It can run on a single GPU or sweep all available CUDA devices.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, r2_score, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split

import lightgbm as lgb


ROOT = Path(__file__).resolve().parents[1]
RAW_SESSIONS_DIR = ROOT / "data" / "sessions"
PROCESSED_SESSIONS_DIR = ROOT / "data" / "processed" / "sessions"
OUTPUT_DIR = ROOT / "training" / "artifacts"


def detect_gpus() -> list[int]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        gpus = [int(x.strip()) for x in out.splitlines() if x.strip()]
        return gpus if gpus else [0]
    except Exception:
        return [0]


def flatten_numeric_dict(d: dict[str, Any]) -> dict[str, float | int]:
    flat: dict[str, float | int] = {}
    for key, value in d.items():
        if value is None:
            continue
        if isinstance(value, dict):
            flat.update(flatten_numeric_dict(value))
        elif isinstance(value, (int, float, np.integer, np.floating)):
            flat[str(key)] = float(value)
    return flat


def ensure_float(value: Any) -> float:
    if value is None:
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def build_dataset() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    if not PROCESSED_SESSIONS_DIR.exists():
        raise FileNotFoundError(f"Processed sessions directory not found: {PROCESSED_SESSIONS_DIR}")

    for group_dir in sorted(PROCESSED_SESSIONS_DIR.iterdir()):
        if not group_dir.is_dir():
            continue
        for session_dir in sorted(group_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            summary_file = session_dir / "summary.json"
            if not summary_file.exists():
                continue
            try:
                summary = json.loads(summary_file.read_text())
            except Exception:
                continue

            session_id = str(summary.get("session_id") or session_dir.name)
            raw_session_dir = RAW_SESSIONS_DIR / session_id
            meta_file = raw_session_dir / "meta.json"
            survey_file = raw_session_dir / "survey.json"
            if not meta_file.exists() or not survey_file.exists():
                continue

            try:
                meta = json.loads(meta_file.read_text())
                survey = json.loads(survey_file.read_text())
            except Exception:
                continue

            stress = survey.get("stress")
            hurry = survey.get("hurry")
            if stress is None:
                continue

            condition = str(summary.get("condition") or meta.get("condition") or "unknown")
            started_at = ensure_float(meta.get("started_at"))
            ended_at = ensure_float(meta.get("ended_at"))
            duration_sec = np.nan if np.isnan(started_at) or np.isnan(ended_at) else float(ended_at - started_at)

            sample: dict[str, Any] = {
                "session_id": session_id,
                "condition": condition,
                "group": str(summary.get("group") or meta.get("group") or condition),
                "order_index": ensure_float(meta.get("order_index")),
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_sec": duration_sec,
                "stress": int(stress),
                "hurry": ensure_float(hurry),
                "is_threat": int(condition in {"scam", "intruder"}),
                "video_status": str((summary.get("video") or {}).get("status") or "unknown"),
                "keyboard_dimension": ensure_float(summary.get("keyboard_dimension")),
                "keyboard_mask": int(bool(summary.get("keyboard_mask"))),
                "issues_count": len(summary.get("issues") or []),
                "elapsed_seconds": ensure_float(summary.get("elapsed_seconds")),
            }

            rows_dict = summary.get("rows") or {}
            artifacts_dict = summary.get("artifacts") or {}
            for key, value in flatten_numeric_dict(rows_dict).items():
                sample[f"rows_{key}"] = value
            for key, value in flatten_numeric_dict(artifacts_dict).items():
                sample[f"artifacts_{key}"] = value

            rows.append(sample)

    if not rows:
        raise ValueError("No usable session rows were produced from processed data.")

    df = pd.DataFrame(rows)
    return df


def make_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "session_id",
        "condition",
        "group",
        "video_status",
        "stress",
        "hurry",
        "is_threat",
        "started_at",
        "ended_at",
    }
    features = []
    for col in df.columns:
        if col in excluded:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            features.append(col)
    return features


def save_metric_json(path: Path, metrics: dict[str, Any]) -> None:
    path.write_text(json.dumps(metrics, indent=2, sort_keys=True))


def plot_feature_importance(model: lgb.LGBMModel, feature_names: list[str], out_path: Path) -> None:
    importance = model.feature_importances_
    if len(importance) == 0:
        return
    df_imp = pd.DataFrame({"feature": feature_names, "importance": importance})
    df_imp = df_imp.sort_values("importance", ascending=False).head(15)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(df_imp["feature"][::-1], df_imp["importance"][::-1], color="steelblue")
    ax.set_title("Top feature importances")
    ax.set_xlabel("Importance")
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def evaluate_binary(train_X: pd.DataFrame, test_X: pd.DataFrame, train_y: pd.Series, test_y: pd.Series, gpu_id: int, out_dir: Path) -> dict[str, Any]:
    print(f"\n=== Binary classification on GPU {gpu_id} ===")
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "n_estimators": 500,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "device": "gpu",
        "gpu_platform_id": gpu_id,
        "gpu_device_id": gpu_id,
        "verbosity": -1,
        "seed": 42,
        "num_threads": 8,
    }
    clf = lgb.LGBMClassifier(**params)
    clf.fit(
        train_X,
        train_y,
        eval_set=[(test_X, test_y)],
        eval_metric=["binary_logloss", "auc"],
        callbacks=[lgb.early_stopping(50, verbose=False)],
    )
    pred = clf.predict(test_X)
    proba = clf.predict_proba(test_X)[:, 1]
    metrics = {
        "accuracy": accuracy_score(test_y, pred),
        "precision": precision_score(test_y, pred, zero_division=0),
        "recall": recall_score(test_y, pred, zero_division=0),
        "f1": f1_score(test_y, pred, zero_division=0),
        "auc": float(clf.best_score_["valid_0"]["auc"]),
        "logloss": float(clf.best_score_["valid_0"]["binary_logloss"]),
        "confusion_matrix": confusion_matrix(test_y, pred).tolist(),
    }
    print(json.dumps({"binary": metrics}, sort_keys=True, indent=2))

    model_path = out_dir / f"lightgbm_binary_gpu{gpu_id}.joblib"
    joblib.dump(clf, model_path)
    plot_feature_importance(clf, list(train_X.columns), out_dir / f"feature_importance_gpu{gpu_id}.png")

    return metrics


def evaluate_regression(train_X: pd.DataFrame, test_X: pd.DataFrame, train_y: pd.Series, test_y: pd.Series, gpu_id: int, out_dir: Path) -> dict[str, Any]:
    print(f"\n=== Stress regression on GPU {gpu_id} ===")
    params = {
        "objective": "regression",
        "metric": "mae",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "n_estimators": 500,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "device": "gpu",
        "gpu_platform_id": gpu_id,
        "gpu_device_id": gpu_id,
        "verbosity": -1,
        "seed": 42,
        "num_threads": 8,
    }
    reg = lgb.LGBMRegressor(**params)
    reg.fit(train_X, train_y, eval_set=[(test_X, test_y)], eval_metric=["mae", "rmse"], callbacks=[lgb.early_stopping(50, verbose=False)])
    pred = reg.predict(test_X)
    metrics = {
        "mae": mean_absolute_error(test_y, pred),
        "rmse": float(np.sqrt(mean_squared_error(test_y, pred))),
        "r2": r2_score(test_y, pred),
        "mean_abs_error": float(mean_absolute_error(test_y, pred)),
    }
    print(json.dumps({"regression": metrics}, sort_keys=True, indent=2))

    model_path = out_dir / f"lightgbm_regression_gpu{gpu_id}.joblib"
    joblib.dump(reg, model_path)
    plot_feature_importance(reg, list(train_X.columns), out_dir / f"regression_feature_importance_gpu{gpu_id}.png")

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train LightGBM session models on GPU")
    parser.add_argument("--gpu-device", type=int, default=None, help="Specific GPU id (default: auto detect)")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR), help="Directory for experiments")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = build_dataset()
    feature_cols = make_feature_columns(df)
    if not feature_cols:
        raise ValueError("No usable numeric feature columns were found in the session dataset.")

    print(f"Built dataset with {len(df)} rows and {len(feature_cols)} feature columns.")
    print("Feature columns:")
    for col in feature_cols[:20]:
        print(f" - {col}")
    print(f"... total {len(feature_cols)}")

    gpu_ids = [args.gpu_device] if args.gpu_device is not None else detect_gpus()
    if args.gpu_device is not None:
        gpu_ids = [args.gpu_device]

    summary: dict[str, Any] = {
        "dataset_rows": int(len(df)),
        "feature_columns": feature_cols,
        "gpus_used": gpu_ids,
        "binary": {},
        "regression": {},
    }

    for gpu_id in gpu_ids:
        print(f"\n### Running experiment on GPU {gpu_id} ###")
        X = df[feature_cols].fillna(0.0)
        y_binary = df["is_threat"]
        y_regression = df["stress"]

        Xb_train, Xb_test, yb_train, yb_test = train_test_split(
            X, y_binary, test_size=0.2, stratify=y_binary, random_state=args.seed
        )
        Xr_train, Xr_test, yr_train, yr_test = train_test_split(
            X, y_regression, test_size=0.2, random_state=args.seed
        )

        summary["binary"][str(gpu_id)] = evaluate_binary(Xb_train, Xb_test, yb_train, yb_test, gpu_id, output_dir)
        summary["regression"][str(gpu_id)] = evaluate_regression(Xr_train, Xr_test, yr_train, yr_test, gpu_id, output_dir)

    save_metric_json(output_dir / "lightgbm_summary.json", summary)
    print("\n=== FINAL SUMMARY ===")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
