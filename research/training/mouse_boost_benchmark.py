"""Compare CatBoost and XGBoost for GUIDÆTA mouse verification.

Enrollment uses task 1. Probes use tasks 2/3; users are disjoint across train,
validation and test. A scaler is fitted only on training users, before profiles
and genuine/impostor pairs are constructed.

    /venv/main/bin/python -m training.mouse_boost_benchmark
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import roc_auc_score, roc_curve
from xgboost import XGBClassifier

DATA = Path("/workspace/datasets/guidaeta")
OUTPUT = Path(__file__).parent / "artifacts" / "mouse_boost"
CAT_GRID = (
    {"depth": 2, "l2_leaf_reg": 10, "learning_rate": 0.03, "iterations": 500},
    {"depth": 3, "l2_leaf_reg": 10, "learning_rate": 0.03, "iterations": 900},
    {"depth": 4, "l2_leaf_reg": 20, "learning_rate": 0.02, "iterations": 900},
    {"depth": 5, "l2_leaf_reg": 5, "learning_rate": 0.04, "iterations": 600},
)
XGB_GRID = (
    {"max_depth": 2, "min_child_weight": 10, "learning_rate": 0.03, "n_estimators": 500},
    {"max_depth": 3, "min_child_weight": 10, "learning_rate": 0.03, "n_estimators": 700},
    {"max_depth": 4, "min_child_weight": 20, "learning_rate": 0.02, "n_estimators": 700},
    {"max_depth": 3, "min_child_weight": 3, "learning_rate": 0.05, "n_estimators": 400},
)


def load_data(root: Path = DATA) -> tuple[pd.DataFrame, list[str]]:
    meta = json.loads((root / "mouse_model_meta.json").read_text())
    features = meta["FEAT_COLS"]
    frame = pd.read_parquet(root / "mouse_session_features.parquet")
    required = {"user_id", "task_no", "session_id", *features}
    if missing := required - set(frame.columns):
        raise ValueError(f"Missing mouse columns: {sorted(missing)}")
    if frame.session_id.duplicated().any():
        raise ValueError("Duplicate mouse session IDs")
    if not np.isfinite(frame[features].to_numpy(dtype=float)).all():
        raise ValueError("Non-finite mouse features")
    return frame, features


def scale_from_training(frame: pd.DataFrame, features: list[str], train_users: set[int]
                       ) -> tuple[np.ndarray, np.ndarray]:
    x = frame.loc[frame.user_id.isin(train_users), features].to_numpy(float)
    center = np.median(x, axis=0)
    # One global robust scale per feature, NOT a scale computed from the probe's true owner.
    scale = np.percentile(x, 75, axis=0) - np.percentile(x, 25, axis=0)
    scale[scale < 1e-6] = 1.0
    return center, scale


def pair_data(frame: pd.DataFrame, features: list[str], users: set[int],
              center: np.ndarray, scale: np.ndarray, seed: int, negatives: int = 5
              ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sub = frame.loc[frame.user_id.isin(users)].copy()
    values = np.clip((sub[features].to_numpy(float) - center) / scale, -8, 8)
    # Enrollment from task 1 only. Never use probe rows to form a profile.
    sub["_idx"] = np.arange(len(sub))
    enroll = sub.loc[sub.task_no == 1]
    profiles = {int(u): np.median(values[g._idx.to_numpy()], axis=0)
                for u, g in enroll.groupby("user_id")}
    pool = np.array(sorted(profiles))
    if len(pool) < 2:
        raise ValueError("At least two enrollment users are needed in each split")
    probes = sub.loc[sub.task_no.isin((2, 3)) & sub.user_id.isin(pool)]
    rng = np.random.default_rng(seed)
    x_rows, labels, probe_ids = [], [], []
    for _, row in probes.iterrows():
        v = values[int(row["_idx"])]
        owner = int(row["user_id"])
        other_users = rng.choice(pool[pool != owner], min(negatives, len(pool) - 1), replace=False)
        for claimed in (owner, *other_users):
            # Both genuine and impostor pair use *the same* probe features.
            x_rows.append(np.abs(v - profiles[int(claimed)]))
            labels.append(int(claimed == owner))
            probe_ids.append(int(row["session_id"]))
    if not x_rows:
        raise ValueError("No probes with task-1 enrollment")
    return np.asarray(x_rows, np.float32), np.asarray(labels), np.asarray(probe_ids)


def metrics(y: np.ndarray, score: np.ndarray) -> dict[str, float]:
    if len(np.unique(y)) != 2:
        raise ValueError("Both genuine and impostor pairs are needed for AUC")
    fpr, tpr, _ = roc_curve(y, score)
    i = np.argmin(np.abs(fpr - (1 - tpr)))
    return {"auc": float(roc_auc_score(y, score)), "eer": float((fpr[i] + 1 - tpr[i]) / 2)}


def make_model(kind: str, params: dict, seed: int):
    if kind == "catboost":
        return CatBoostClassifier(**params, loss_function="Logloss", verbose=False, thread_count=4,
                                  random_seed=seed, allow_writing_files=False)
    return XGBClassifier(**params, objective="binary:logistic", tree_method="hist",
                         n_jobs=4, random_state=seed, subsample=0.8, colsample_bytree=0.9,
                         reg_lambda=10, eval_metric="logloss")


def person_folds(frame: pd.DataFrame, folds: int, seed: int) -> list[tuple[set[int], set[int], set[int]]]:
    rng = np.random.default_rng(seed)
    enrolled = set(frame.loc[frame.task_no == 1, "user_id"])
    buckets: list[list[int]] = [[] for _ in range(folds)]
    for cohort in (sorted(enrolled), sorted(set(frame.user_id) - enrolled)):
        rng.shuffle(cohort)
        for i, user in enumerate(cohort):
            buckets[i % folds].append(user)
    assignments = []
    for fold in range(folds):
        test = set(buckets[fold])
        rest = set(frame.user_id) - test
        enrolled_rest = sorted(rest & enrolled)
        missing_rest = sorted(rest - enrolled)
        rng.shuffle(enrolled_rest)
        rng.shuffle(missing_rest)
        val_enrolled = max(2, round(len(enrolled_rest) * 0.2))
        val = set(enrolled_rest[:val_enrolled] + missing_rest[:round(len(missing_rest) * 0.2)])
        assignments.append((rest - val, val, test))
    return assignments


def run(frame: pd.DataFrame, features: list[str], folds: int = 5, seed: int = 42,
        negatives: int = 5) -> dict:
    users = sorted(frame.user_id.unique().tolist())
    if folds < 3 or folds > len(users) // 4:
        raise ValueError("Use 3 or more folds with at least four users per split")
    assignments = person_folds(frame, folds, seed)
    results = []
    for fold, (tr, va, te) in enumerate(assignments):
        tr, va, te = set(tr), set(va), set(te)
        if tr & va or tr & te or va & te:
            raise AssertionError("Overlapping user splits")
        center, scale = scale_from_training(frame, features, tr)
        xtr, ytr, _ = pair_data(frame, features, tr, center, scale, seed + fold, negatives)
        xva, yva, _ = pair_data(frame, features, va, center, scale, seed + fold + 100, negatives)
        xte, yte, test_ids = pair_data(frame, features, te, center, scale, seed + fold + 200, negatives)
        row = {"fold": fold, "users": {"train": len(tr), "val": len(va), "test": len(te)},
               "pairs": {"train": len(ytr), "val": len(yva), "test": len(yte)},
               "test_probe_sessions": len(np.unique(test_ids)), "models": {}}
        for kind, grid in (("catboost", CAT_GRID), ("xgboost", XGB_GRID)):
            candidates = []
            for params in grid:
                model = make_model(kind, params, seed + fold)
                model.fit(xtr, ytr)
                candidates.append(metrics(yva, model.predict_proba(xva)[:, 1])["auc"])
            choice = int(np.argmax(candidates))
            # Refit on both train + validation, then evaluate the untouched test users once.
            center_final, scale_final = scale_from_training(frame, features, tr | va)
            xfit, yfit, _ = pair_data(frame, features, tr | va, center_final, scale_final,
                                     seed + fold + 300, negatives)
            xte_final, yte_final, _ = pair_data(frame, features, te, center_final, scale_final,
                                                seed + fold + 200, negatives)
            if not np.array_equal(yte, yte_final):
                raise AssertionError("Test labels changed after re-scaling")
            if kind == "catboost":
                row["l1"] = metrics(yte_final, -xte_final.sum(axis=1))
            model = make_model(kind, grid[choice], seed + fold)
            model.fit(xfit, yfit)
            score = model.predict_proba(xte_final)[:, 1]
            row["models"][kind] = {"choice": choice, "params": grid[choice],
                                   "validation_auc": candidates[choice], **metrics(yte_final, score)}
        results.append(row)
        print(f"fold {fold}: L1={row['l1']['auc']:.3f}, "
              f"CB={row['models']['catboost']['auc']:.3f}, "
              f"XGB={row['models']['xgboost']['auc']:.3f}", flush=True)
    aggregate = {}
    for name in ("l1", "catboost", "xgboost"):
        fold_metrics = [r["l1"] if name == "l1" else r["models"][name] for r in results]
        aggregate[name] = {key: {"mean": float(np.mean([m[key] for m in fold_metrics])),
                                 "std": float(np.std([m[key] for m in fold_metrics]))}
                           for key in ("auc", "eer")}
    return {"protocol": "task1 enrollment, task2/3 probes; disjoint users; inner validation "
            "selects parameters, outer test once; 5 impostors/probe drawn within split",
            "n_users": len(users), "folds": folds, "seed": seed, "negatives": negatives,
            "features": features, "results": results, "summary": aggregate}


def fit_final(frame: pd.DataFrame, features: list[str], report: dict, out: Path) -> None:
    """Fit deployable GUIDÆTA models; never claim their full-data fit is a test metric."""
    users = set(frame.user_id)
    center, scale = scale_from_training(frame, features, users)
    x, y, _ = pair_data(frame, features, users, center, scale, report["seed"] + 300,
                        report["negatives"])
    out.mkdir(parents=True, exist_ok=True)
    chosen = {}
    for kind, grid, suffix in (("catboost", CAT_GRID, "cbm"), ("xgboost", XGB_GRID, "json")):
        counts = Counter(r["models"][kind]["choice"] for r in report["results"])
        choice = max(range(len(grid)), key=lambda i: (counts[i], -i))
        model = make_model(kind, grid[choice], report["seed"])
        model.fit(x, y)
        model.save_model(str(out / f"mouse_{kind}.{suffix}"))
        chosen[kind] = {"choice": choice, "params": grid[choice]}
    # Only task-1 sessions may define a claimed user's profile. New users must enroll first.
    enroll = frame.loc[frame.task_no == 1]
    profile_frame = enroll.groupby("user_id")[features].median()
    profile_frame.to_parquet(out / "enrollment_profiles.parquet")
    (out / "model_metadata.json").write_text(json.dumps({
        "source": "GUIDÆTA mouse_session_features.parquet",
        "features": features, "center": center.tolist(), "scale": scale.tolist(),
        "profile": "median of task-1 raw features; pair = abs(clip(probe) - clip(profile))",
        "model_choices": chosen, "evaluation": "comparison.json (disjoint-user CV, not full fit)",
    }, indent=2))


def score_mouse(probe: dict[str, float], enrollment: pd.DataFrame, model_dir: Path = OUTPUT,
                kind: str = "catboost") -> float:
    """Probability of a genuine match for raw GUIDÆTA-schema probe and enrollment sessions.

    The caller supplies the claimed person's task-1 rows, not the probe person's true identity.
    Other mouse feature schemas (including HackYeah's 10 s windows) are incompatible.
    """
    if enrollment.empty:
        raise ValueError("A claimed user's task-1 enrollment is required")
    if "task_no" in enrollment and not enrollment["task_no"].eq(1).all():
        raise ValueError("Enrollment must contain task-1 sessions only")
    if "user_id" in enrollment and enrollment["user_id"].nunique() != 1:
        raise ValueError("Enrollment must belong to exactly one claimed user")
    meta = json.loads((model_dir / "model_metadata.json").read_text())
    cols = meta["features"]
    if missing := set(cols) - set(probe):
        raise ValueError(f"Missing probe features: {sorted(missing)}")
    if missing := set(cols) - set(enrollment.columns):
        raise ValueError(f"Missing enrollment features: {sorted(missing)}")
    x = np.asarray([probe[c] for c in cols], dtype=float)
    p = enrollment[cols].median().to_numpy(float)
    if not np.isfinite(x).all() or not np.isfinite(p).all():
        raise ValueError("Non-finite mouse features")
    center = np.asarray(meta["center"])
    scale = np.asarray(meta["scale"])
    delta = np.abs(np.clip((x - center) / scale, -8, 8)
                   - np.clip((p - center) / scale, -8, 8)).reshape(1, -1)
    if kind == "catboost":
        model = CatBoostClassifier()
        model.load_model(str(model_dir / "mouse_catboost.cbm"))
    elif kind == "xgboost":
        model = XGBClassifier()
        model.load_model(str(model_dir / "mouse_xgboost.json"))
    else:
        raise ValueError(f"Unsupported model: {kind}")
    return float(model.predict_proba(delta)[:, 1][0])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--output", type=Path, default=OUTPUT / "comparison.json")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-final", action="store_true")
    args = ap.parse_args()
    frame, features = load_data(args.data)
    report = run(frame, features, args.folds, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    if not args.no_final:
        fit_final(frame, features, report, args.output.parent)
    print(json.dumps(report["summary"], indent=2))
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
