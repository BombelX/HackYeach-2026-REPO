"""Train the fusion transformer with person-grouped CV (folds run in parallel on all GPUs).

    /venv/main/bin/python -m training.fusion.train            # 5-fold CV + final model
    /venv/main/bin/python -m training.fusion.train --folds 5 --seeds 3 --gpus 0,1,2,3

Each fold: ~8 test people, ~7 validation people (early stopping), the rest train. A person is
always entirely on one side; pairs are only built between people of the same split.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve

from training.fusion.data import (
    INPUT_DIMS, Normalizer, Pair, build_profiles, make_pairs, pair_tensors, to_torch,
)
from training.fusion.features import CONTEXT_PAIR_FEATURES, ROOT, load_windows
from training.fusion.model import TOKENS, FusionTransformer, count_parameters
from training.fusion.network import NETWORK_CONFIG, attach_crossfit_network
from training.fusion.risk import TARGET_RECALL, alarm_counts, risk_score, select_threshold

ART = ROOT / "training" / "artifacts" / "fusion"
# token index in mask: 0 kb, 1 mouse, 2 pulse, 3 face, 4 context, 5 profile
DROPOUT_P = {0: 0.1, 1: 0.1, 2: 0.3, 3: 0.3, 4: 0.2}
CONFIG = dict(dim=128, heads=4, layers=2, ff=256, dropout=0.1)
VARIANTS = {
    "baseline": (CONFIG, 0.05),
    "compact": (dict(dim=96, heads=4, layers=2, ff=192, dropout=0.2), 0.1),
    "wider": (dict(dim=160, heads=4, layers=2, ff=320, dropout=0.2), 0.1),
}


# ---------------------------------------------------------------- metrics
def _auc(y, s):
    y, s = np.asarray(y), np.asarray(s)
    return float(roc_auc_score(y, s)) if len(np.unique(y)) == 2 else float("nan")


def _ap(y, s):
    y, s = np.asarray(y), np.asarray(s)
    return float(average_precision_score(y, s)) if len(np.unique(y)) == 2 else float("nan")


def _eer(y, s):
    y, s = np.asarray(y), np.asarray(s)
    if len(np.unique(y)) < 2:
        return float("nan")
    fpr, tpr, _ = roc_curve(y, s)
    fnr = 1 - tpr
    i = int(np.nanargmin(np.abs(fnr - fpr)))
    return float((fpr[i] + fnr[i]) / 2)


def mask_camera(batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Hide camera features in both probe tokens and calm enrollment profile."""
    batch = batch.copy()
    batch["mask"] = batch["mask"].clone()
    batch["mask"][:, 2:4] = 0
    batch["profile_stats"] = batch["profile_stats"].clone()
    start = INPUT_DIMS["mouse_dim"]
    end = start + INPUT_DIMS["pulse_dim"] + INPUT_DIMS["face_dim"]
    batch["profile_stats"][:, start:end] = 0
    batch["profile_stats"][:, -3:-1] = 0  # pulse and face profile availability
    return batch


def scale_device_match(batch: dict[str, torch.Tensor], scale: float,
                       dropout: float = 0.0) -> dict[str, torch.Tensor]:
    """Attenuate pairwise device inputs; optionally hide the whole group during training."""
    if not 0 <= scale <= 1 or not 0 <= dropout < 1:
        raise ValueError("Device-match scale must be in [0, 1] and dropout in [0, 1)")
    if scale == 1 and dropout == 0:
        return batch
    batch = batch.copy()
    batch["ctx"] = batch["ctx"].clone()
    device = batch["ctx"][:, -len(CONTEXT_PAIR_FEATURES):]
    if dropout:
        keep = (torch.rand((len(device), 1), device=device.device) >= dropout).to(device.dtype)
        device.mul_(keep)
    device.mul_(scale)
    return batch


def mask_device_match(batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    return scale_device_match(batch, 0.0)


def pair_scores(model, T, n_pairs: int, mask_tokens: tuple[int, ...] = (),
                camera_off: bool = False, device_scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Session-level score = mean window logit of the pair."""
    model.eval()
    out_n, out_p = [], []
    with torch.no_grad():
        for i in range(0, T["mask"].shape[0], 16384):
            b = {k: v[i:i + 16384] for k, v in T.items()}
            if camera_off:
                b = mask_camera(b)
            b = scale_device_match(b, device_scale)
            if mask_tokens:
                b["mask"] = b["mask"].clone()
                b["mask"][:, list(mask_tokens)] = 0
            o = model(b)
            out_n.append(o["nonowner"].float())
            out_p.append(o["pressure"].float())
    ln, lp, pid = torch.cat(out_n), torch.cat(out_p), T["pair"]
    cnt = torch.zeros(n_pairs, device=ln.device).index_add_(0, pid, torch.ones_like(ln))
    sn = torch.zeros(n_pairs, device=ln.device).index_add_(0, pid, ln) / cnt.clamp(min=1)
    sp = torch.zeros(n_pairs, device=ln.device).index_add_(0, pid, lp) / cnt.clamp(min=1)
    return sn.cpu().numpy(), sp.cpu().numpy()


def cosine_baseline(arrays: dict[str, np.ndarray], n_pairs: int) -> np.ndarray:
    """Per pair: 1 - mean cos(window keyboard embedding, profile keyboard embedding); NaN if unavailable."""
    ok = (arrays["mask"][:, 0] > 0) & (arrays["profile_kb_mask"] > 0)
    cos = (arrays["kb"] * arrays["profile_kb"]).sum(1)
    num = np.bincount(arrays["pair"][ok], weights=cos[ok], minlength=n_pairs)
    cnt = np.bincount(arrays["pair"][ok], minlength=n_pairs)
    out = np.full(n_pairs, np.nan)
    out[cnt > 0] = 1 - num[cnt > 0] / cnt[cnt > 0]
    return out


def evaluate(model, T, arrays, pairs: list[Pair], camera_off: bool = False,
             device_scale: float = 1.0) -> dict:
    n = len(pairs)
    y = np.array([p.nonowner for p in pairs])
    yp = np.array([p.pressure for p in pairs])
    pv = np.array([p.pressure_valid for p in pairs]).astype(bool)
    sn, sp = pair_scores(model, T, n, camera_off=camera_off, device_scale=device_scale)
    sn_noctx, sp_noctx = pair_scores(model, T, n, mask_tokens=(4,),
                                    camera_off=camera_off, device_scale=device_scale)
    sn_no_camera, sp_no_camera = pair_scores(model, T, n, camera_off=True, device_scale=device_scale)
    base = cosine_baseline(arrays, n)
    kb_ok = ~np.isnan(base)
    return {
        "n_pairs": n, "n_nonowner": int(y.sum()), "n_owner": int((1 - y).sum()),
        "n_pressure_pos": int(yp[pv].sum()), "n_pressure_neg": int((1 - yp[pv]).sum()),
        "nonowner_auc": _auc(y, sn), "nonowner_ap": _ap(y, sn), "nonowner_eer": _eer(y, sn),
        "nonowner_auc_no_context": _auc(y, sn_noctx), "nonowner_eer_no_context": _eer(y, sn_noctx),
        "pressure_auc": _auc(yp[pv], sp[pv]), "pressure_ap": _ap(yp[pv], sp[pv]),
        "pressure_auc_no_context": _auc(yp[pv], sp_noctx[pv]),
        "nonowner_auc_no_camera": _auc(y, sn_no_camera),
        "pressure_auc_no_camera": _auc(yp[pv], sp_no_camera[pv]),
        "kb_subset_pairs": int(kb_ok.sum()),
        "kb_cosine_baseline_auc": _auc(y[kb_ok], base[kb_ok]),
        "kb_cosine_baseline_eer": _eer(y[kb_ok], base[kb_ok]),
        "fusion_auc_on_kb_subset": _auc(y[kb_ok], sn[kb_ok]),
        "fusion_no_context_auc_on_kb_subset": _auc(y[kb_ok], sn_noctx[kb_ok]),
        "_scores": {"nonowner": sn.tolist(), "pressure": sp.tolist(), "nonowner_no_context": sn_noctx.tolist(),
                    "kb_cosine": [None if np.isnan(v) else float(v) for v in base],
                    "pairs": [p.__dict__ for p in pairs]},
    }


# ---------------------------------------------------------------- training
def _loss_weights(arrays: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Each pair counts once (1/n per window); classes are balanced to equal total mass."""
    w = arrays["weight"].astype(np.float64)
    y = arrays["nonowner"]
    wn = w.copy()
    for c in (0, 1):
        m = y == c
        if m.any():
            wn[m] *= 0.5 / w[m].sum()
    pv = arrays["pressure_valid"] > 0
    wp = np.zeros_like(w)
    for c in (0, 1):
        m = pv & (arrays["pressure"] == c)
        if m.any():
            wp[m] = w[m] * 0.5 / w[m].sum()
    return wn.astype(np.float32), wp.astype(np.float32)


def validation_loss(model, tensors: dict[str, torch.Tensor], pairs: list[Pair],
                    camera_off: bool = False, device_scale: float = 1.0) -> float:
    """Balanced BCE on session-level logits, with no repeated-window advantage."""
    owner_logits, pressure_logits = pair_scores(
        model, tensors, len(pairs), camera_off=camera_off, device_scale=device_scale)
    nonowner = torch.tensor([p.nonowner for p in pairs], dtype=torch.float32)
    pressure = torch.tensor([p.pressure for p in pairs], dtype=torch.float32)
    valid = torch.tensor([p.pressure_valid for p in pairs], dtype=torch.bool)
    owner_logits = torch.from_numpy(owner_logits)
    pressure_logits = torch.from_numpy(pressure_logits)
    losses = []
    for labels, logits, eligible in ((nonowner, owner_logits, torch.ones_like(valid)),
                                     (pressure, pressure_logits, valid)):
        for label in (0, 1):
            select = eligible & (labels == label)
            if not select.any():
                raise ValueError(f"Validation set has no examples of class {label}")
            losses.append(F.binary_cross_entropy_with_logits(logits[select], labels[select]).item())
    return float(np.mean(losses))


def train_model(sessions, profiles, train_people, val_people, device, seed, epochs=300, patience=60,
                batch=4096, lr=3e-4, min_epochs=20, fixed_epochs: int | None = None,
                config: dict | None = None, weight_decay: float = 0.05,
                camera_off: bool = False, device_scale: float = 1.0,
                device_dropout: float = 0.0):
    if epochs < 1 or patience < 1 or min_epochs < 1:
        raise ValueError("epochs, patience and min_epochs must be positive")
    torch.manual_seed(seed)
    np.random.seed(seed)
    norm = Normalizer.fit([s for s in sessions.values() if s.participant in train_people])
    tr_pairs = make_pairs(sessions, profiles, set(train_people))
    tr_arr = pair_tensors(tr_pairs, sessions, profiles, norm)
    wn, wp = _loss_weights(tr_arr)
    T = to_torch(tr_arr, device)
    T["wn"], T["wp"] = torch.from_numpy(wn).to(device), torch.from_numpy(wp).to(device)
    N = T["mask"].shape[0]
    val = None
    if val_people:
        va_pairs = make_pairs(sessions, profiles, set(val_people))
        va_arr = pair_tensors(va_pairs, sessions, profiles, norm)
        val = (to_torch(va_arr, device), va_pairs)

    model = FusionTransformer(**INPUT_DIMS, **(CONFIG if config is None else config)).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    total = fixed_epochs if fixed_epochs is not None else epochs
    if total < 1:
        raise ValueError("fixed_epochs must be positive")
    drop_p = torch.tensor([DROPOUT_P.get(i, 0.0) for i in range(len(TOKENS))], device=device)
    best, best_state, best_epoch, bad = float("inf"), None, 0, 0
    for epoch in range(total):
        model.train()
        perm = torch.randperm(N, device=device)
        for i in range(0, N, batch):
            idx = perm[i:i + batch]
            b = {k: v[idx] for k, v in T.items()}
            if camera_off:
                b = mask_camera(b)
            b = scale_device_match(b, device_scale, device_dropout)
            # modality dropout: the model must survive without camera / keyboard / context
            keep = (torch.rand_like(b["mask"]) >= drop_p).float()
            b["mask"] = b["mask"] * keep
            out = model(b)
            ln = F.binary_cross_entropy_with_logits(out["nonowner"], b["nonowner"], reduction="none")
            lp = F.binary_cross_entropy_with_logits(out["pressure"], b["pressure"], reduction="none")
            loss = (ln * b["wn"]).sum() * N / len(idx) + (lp * b["wp"]).sum() * N / len(idx)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        if val is not None and epoch + 1 >= min_epochs:
            score = validation_loss(model, *val, camera_off=camera_off, device_scale=device_scale)
            if score < best - 1e-4:
                best, best_epoch, bad = score, epoch + 1, 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
    trained_epochs = epoch + 1
    if best_state is not None:
        model.load_state_dict(best_state)
    else:
        best_epoch = trained_epochs
    return model, norm, best_epoch, trained_epochs, (best if val is not None else None)


def _run_fold(args) -> dict:
    fold, seed, gpu, train_p, val_p, test_p, kw = args
    device = f"cuda:{gpu}" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(4)
    sessions = load_windows(workers=1)
    attach_crossfit_network(sessions, set(train_p), seed)
    profiles = build_profiles(sessions)
    t0 = time.time()
    model, norm, best_epoch, trained_epochs, best_val_loss = train_model(
        sessions, profiles, train_p, val_p, device, seed, **kw)
    camera_off = kw["camera_off"]
    device_scale = kw["device_scale"]
    va_pairs = make_pairs(sessions, profiles, set(val_p))
    va_arr = pair_tensors(va_pairs, sessions, profiles, norm)
    val_nonowner_logits, val_pressure_logits = pair_scores(
        model, to_torch(va_arr, device), len(va_pairs),
        camera_off=camera_off, device_scale=device_scale)
    threshold = select_threshold(va_pairs, risk_score(val_nonowner_logits, val_pressure_logits))
    te_pairs = make_pairs(sessions, profiles, set(test_p))
    te_arr = pair_tensors(te_pairs, sessions, profiles, norm)
    m = evaluate(model, to_torch(te_arr, device), te_arr, te_pairs,
                 camera_off=camera_off, device_scale=device_scale)
    te_n, te_p = pair_scores(model, to_torch(te_arr, device), len(te_pairs),
                             camera_off=camera_off, device_scale=device_scale)
    m["review_threshold"] = threshold
    m["review_counts"] = alarm_counts(te_pairs, risk_score(te_n, te_p), threshold)
    m.update(fold=fold, seed=seed, best_epoch=best_epoch, trained_epochs=trained_epochs,
             best_val_loss=best_val_loss, seconds=round(time.time() - t0, 1),
             test_people=sorted(test_p), val_people=sorted(val_p), n_train_people=len(train_p),
             network_model="fold_local_hgb")
    return m


def person_folds(people: list[str], profiles: dict, k: int, seed: int) -> list[tuple[list, list, list]]:
    """Stratified so every fold gets people with a calm profile (needed for owner/impostor pairs)."""
    rng = np.random.default_rng(seed)
    with_p = [p for p in people if p in profiles]
    without = [p for p in people if p not in profiles]
    rng.shuffle(with_p)
    rng.shuffle(without)
    buckets = [[] for _ in range(k)]
    for i, p in enumerate(with_p + without):
        buckets[i % k].append(p)
    out = []
    for f in range(k):
        test = buckets[f]
        rest = [p for p in with_p + without if p not in test]
        rest_prof = [p for p in rest if p in profiles]
        n_val = max(2, round(len(rest) * 0.17))
        val = rest_prof[:max(2, round(n_val * len(rest_prof) / max(len(rest), 1)))]
        val += [p for p in rest if p not in profiles][:n_val - len(val)]
        train = [p for p in rest if p not in val]
        out.append((train, val, test))
    return out


def _summarise(results: list[dict]) -> dict:
    keys = [k for k in results[0] if isinstance(results[0][k], float) and not k.startswith("_")]
    agg = {}
    for k in keys:
        v = np.array([r[k] for r in results], float)
        agg[k] = {"mean": float(np.nanmean(v)), "std": float(np.nanstd(v))}
    # pooled across folds (all test pairs together; scores are per-fold logits, so this is approximate)
    return agg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--gpus", default="0,1,2,3")
    ap.add_argument("--epochs", type=int, default=300, help="Maximum epochs in each CV fold")
    ap.add_argument("--patience", type=int, default=60, help="Epochs without validation-loss improvement")
    ap.add_argument("--min-epochs", type=int, default=20, help="First epoch eligible as best checkpoint")
    ap.add_argument("--rebuild-cache", action="store_true")
    ap.add_argument("--no-final", action="store_true")
    ap.add_argument("--no-camera", action="store_true",
                    help="Train and evaluate without pulse/face/posture, including their enrollment statistics")
    ap.add_argument("--no-device-match", action="store_true",
                    help="Train and evaluate without any pairwise device-match/known features")
    ap.add_argument("--device-match-scale", type=float, default=1.0,
                    help="Multiply all nine pairwise device features by this value (0..1)")
    ap.add_argument("--device-match-dropout", type=float, default=0.0,
                    help="Chance of hiding all nine device features per training window (0..1)")
    ap.add_argument("--variant", choices=VARIANTS, default="baseline",
                    help="Fixed architecture/regularization; compare on identical person splits")
    ap.add_argument("--output-dir", type=Path, default=ART,
                    help="Keep exploratory reports and checkpoints separate from the deployed model")
    args = ap.parse_args()
    if args.epochs < args.min_epochs:
        ap.error("--epochs must be >= --min-epochs")
    if not 0 <= args.device_match_scale <= 1 or not 0 <= args.device_match_dropout < 1:
        ap.error("--device-match-scale must be in [0,1] and --device-match-dropout in [0,1)")
    if args.no_device_match and (args.device_match_scale != 1 or args.device_match_dropout):
        ap.error("--no-device-match cannot be combined with device scale or dropout")
    device_scale = 0.0 if args.no_device_match else args.device_match_scale
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config, weight_decay = VARIANTS[args.variant]

    sessions = load_windows(workers=32, rebuild=args.rebuild_cache)
    profiles = build_profiles(sessions)
    people = sorted({s.participant for s in sessions.values()})
    model = FusionTransformer(**INPUT_DIMS, **config)
    n_params = count_parameters(model)
    assert n_params < 1_000_000, n_params
    print(f"variant={args.variant} sessions={len(sessions)} people={len(people)} "
          f"profiles={len(profiles)} params={n_params}")

    gpus = [int(g) for g in args.gpus.split(",") if g != ""] or [0]
    kw = dict(epochs=args.epochs, patience=args.patience, min_epochs=args.min_epochs,
              config=config, weight_decay=weight_decay,
              camera_off=args.no_camera, device_scale=device_scale,
              device_dropout=args.device_match_dropout)
    jobs = []
    for seed in range(args.seeds):
        for f, (tr, va, te) in enumerate(person_folds(people, profiles, args.folds, seed)):
            jobs.append((f, seed, gpus[len(jobs) % len(gpus)], tr, va, te, kw))
    ctx = mp.get_context("spawn")
    with ctx.Pool(min(len(jobs), 4 * len(gpus))) as pool:
        results = pool.map(_run_fold, jobs, chunksize=1)
    for r in results:
        print(f"seed {r['seed']} fold {r['fold']}: nonowner AUC {r['nonowner_auc']:.3f} "
              f"(no ctx {r['nonowner_auc_no_context']:.3f}) | kb-cos {r['kb_cosine_baseline_auc']:.3f} vs "
              f"fusion {r['fusion_auc_on_kb_subset']:.3f} on {r['kb_subset_pairs']} pairs | "
              f"pressure AUC {r['pressure_auc']:.3f} (no ctx {r['pressure_auc_no_context']:.3f}) "
              f"best epoch {r['best_epoch']}/{r['trained_epochs']} (val loss {r['best_val_loss']:.4f})")
    summary = _summarise(results)
    best_epochs = [r["best_epoch"] for r in results]
    report = {"params": n_params, "config": config, "variant": args.variant,
              "camera_off": args.no_camera, "device_match_off": args.no_device_match,
              "device_match_scale": device_scale, "device_match_dropout": args.device_match_dropout,
              "weight_decay": weight_decay, "network_model": "fold_local_hgb_oof_train",
              "network_config": NETWORK_CONFIG, "dropout_p": DROPOUT_P, "folds": args.folds,
              "selection": "minimum balanced session-level validation BCE",
              "review_target_recall_on_validation": TARGET_RECALL,
              "review_policy": "threshold selected on validation for scam owners AND impostors; "
                               "alerts require human verification, not automatic blocking",
              "max_epochs": args.epochs, "patience": args.patience, "min_epochs": args.min_epochs,
              "seeds": args.seeds, "n_sessions": len(sessions), "n_people": len(people),
              "n_profiles": len(profiles), "summary": summary, "best_epochs": best_epochs,
              "folds_detail": [{k: v for k, v in r.items() if k != "_scores"} for r in results]}
    (args.output_dir / "cv_summary.json").write_text(json.dumps(report, indent=2))
    (args.output_dir / "cv_scores.json").write_text(json.dumps([{"fold": r["fold"], "seed": r["seed"], **r["_scores"]}
                                                                for r in results]))
    print(json.dumps(summary, indent=2))
    for seed in range(args.seeds):
        subset = [r["review_counts"] for r in results if r["seed"] == seed]
        print(f"seed {seed} review at validation-selected thresholds:",
              {category: {key: sum(f[category][key] for f in subset)
                          for key in ("total", "flagged", "missed")}
               for category in ("scam_owner", "impostor", "natural_intruder", "normal_owner")})

    if not args.no_final:
        # Reserve people for a deployable threshold; calibrating on training people
        # would give an optimistically high threshold and missed frauds.
        _, calibration_people, _ = person_folds(people, profiles, args.folds, 42)[0]
        final_train = [p for p in people if p not in calibration_people]
        device = f"cuda:{gpus[0]}" if torch.cuda.is_available() else "cpu"
        network_model = attach_crossfit_network(sessions, set(final_train))
        model, norm, final_epoch, _, _ = train_model(
            sessions, profiles, final_train, calibration_people, device, seed=0, **kw)
        calibration_pairs = make_pairs(sessions, profiles, set(calibration_people))
        calibration_arrays = pair_tensors(calibration_pairs, sessions, profiles, norm)
        cn, cp = pair_scores(model, to_torch(calibration_arrays, device), len(calibration_pairs),
                             camera_off=args.no_camera, device_scale=device_scale)
        calibration_scores = risk_score(cn, cp)
        final_threshold = select_threshold(calibration_pairs, calibration_scores)
        report["deployment_calibration"] = {
            "train_people": len(final_train), "held_out_calibration_people": calibration_people,
            "target_recall": TARGET_RECALL, "threshold": final_threshold,
            "counts": alarm_counts(calibration_pairs, calibration_scores, final_threshold),
            "warning": "Threshold selection reused the early-stopping group; recall is not guaranteed.",
        }
        (args.output_dir / "cv_summary.json").write_text(json.dumps(report, indent=2))
        torch.save({"state_dict": model.cpu().state_dict(), "config": config, "input_dims": INPUT_DIMS,
                    "normalizer": norm.state(), "epochs": final_epoch, "params": n_params,
                    "tokens": TOKENS, "network_model": network_model,
                    "network_config": NETWORK_CONFIG,
                    "camera_off": args.no_camera,
                    "device_match_off": args.no_device_match,
                    "device_match_scale": device_scale,
                    "device_match_dropout": args.device_match_dropout,
                    "review_threshold": final_threshold,
                    "review_target_recall": TARGET_RECALL,
                    "calibration_people": calibration_people}, args.output_dir / "fusion_model.pt")
        print(f"saved {args.output_dir / 'fusion_model.pt'} "
              f"(trained on {len(final_train)} people; {len(calibration_people)} held out "
              f"for early stopping/threshold; best epoch {final_epoch}; review threshold {final_threshold:.4f})")


if __name__ == "__main__":
    main()
