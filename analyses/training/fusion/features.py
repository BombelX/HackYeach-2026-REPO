"""Per-window (10 s) features for the fusion model, built only from preprocessed numbers.

Everything here is computed from `data/processed`. Nothing reads survey answers,
condition/group labels, chat markers or the `chat_reply` field, because those
identify the scenario directly (label leakage).
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROCESSED_ROOT = ROOT / "data" / "processed"

WINDOW_MS = 10_000.0
STRIDE_MS = 5_000.0
STROKE_GAP_MS = 300.0
KB_DIM = 128
CONDITIONS = ("calm_1", "dictation", "scam", "intruder")
# Scenario-specific UI elements; using them would let the model read the label.
LEAKY_FIELDS = {"chat_reply"}

MOUSE_FEATURES = [
    "log_n_moves", "log_path_px", "speed_med", "speed_std", "speed_p90", "accel_med",
    "turn_med", "straightness_med", "log_stroke_len_med", "log_n_strokes", "idle_frac",
    "log_n_down", "log_n_click", "hold_ms_med", "log_n_wheel", "log_wheel_mag",
    "touch_frac", "speed_entropy", "time_to_first_move",
]
PULSE_FEATURES = ["bpm_mean", "bpm_std", "bpm_slope", "spectral_conc", "face_crop_valid_frac", "log_n_samples"]
BLENDSHAPES = [
    "browDownLeft", "browDownRight", "browInnerUp", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "eyeLookDownLeft",
    "eyeLookDownRight", "jawOpen", "mouthClose", "mouthFrownLeft", "mouthFrownRight",
    "mouthPressLeft", "mouthPressRight", "mouthSmileLeft", "mouthSmileRight", "cheekSquintLeft",
]
POSTURE = ["head_shoulder_ratio", "head_tilt_degrees", "shoulder_tilt_degrees", "shoulder_width_normalized"]
FACE_FEATURES = (
    [f"{b}_mean" for b in BLENDSHAPES] + [f"{b}_std" for b in BLENDSHAPES]
    + [f"{p}_mean" for p in POSTURE] + [f"{p}_std" for p in POSTURE]
    + ["head_speed", "head_x_std", "head_y_std", "head_scale_std", "face_valid_frac"]
)
FIELD_GROUPS = {
    "credentials": {"client_id", "password"},
    "account": {"nrb", "payee"},
    "amount": {"amount"},
    "title": {"title"},
    "sms": {"sms_code"},
}
MARKER_FEATURES = (["log_paste", "log_copy", "log_cut", "log_window_blur", "log_hidden", "log_field_focus"]
                   + [f"log_input_{g}" for g in FIELD_GROUPS])
N_MARKER_FEATURES = len(MARKER_FEATURES)
# Connection quality only. Request *counts* are deliberately excluded: every server_request in
# network.parquet is the recorder uploading /face,/events,/video,/net for this study, so their
# number tracks session length and chat activity (scam) rather than anything a bank would see.
NETWORK_WINDOW_FEATURES = ["log_rtt_med", "log_rtt_jitter", "log_req_latency_med", "log_req_latency_p95",
                           "req_error_frac", "rtt_in_window"]
CONTEXT_WINDOW_FEATURES = MARKER_FEATURES + NETWORK_WINDOW_FEATURES
NET_EMB_DIM = 64  # slot for a future network-model embedding (see training/fusion/README.md)
DEVICE_KEYS = ["platform", "userAgent", "screen", "devicePixelRatio", "timezone", "language",
               "hardwareConcurrency", "maxTouchPoints"]
CONTEXT_PAIR_FEATURES = [f"same_{k}" for k in DEVICE_KEYS] + ["device_known"]
CONTEXT_FEATURES = CONTEXT_WINDOW_FEATURES + CONTEXT_PAIR_FEATURES


@dataclass
class SessionWindows:
    session_id: str
    participant: str
    condition: str
    victim: str | None
    starts: np.ndarray                    # (N,) window start, ms since session start
    kb: np.ndarray                        # (N, 128) L2-normalised frozen keyboard embedding
    kb_mask: np.ndarray                   # (N,)
    mouse: np.ndarray
    mouse_mask: np.ndarray
    pulse: np.ndarray
    pulse_mask: np.ndarray
    face: np.ndarray
    face_mask: np.ndarray
    ctx: np.ndarray                       # (N, len(CONTEXT_WINDOW_FEATURES))
    device: dict[str, Any] = field(default_factory=dict)
    split_ms: float | None = None         # calm only: enrolment (< split) / probe (>= split)
    kb_windows: list[tuple[float, float, float, np.ndarray]] = field(default_factory=list)
    net_emb: np.ndarray | None = None     # (N, NET_EMB_DIM) from a future network model, None = absent
    net_mask: np.ndarray | None = None    # (N,)


@dataclass
class Profile:
    participant: str
    session_id: str
    kb: np.ndarray
    kb_mask: float
    mouse: np.ndarray
    mouse_mask: float
    pulse: np.ndarray
    pulse_mask: float
    face: np.ndarray
    face_mask: float
    device: dict[str, Any]


def _read(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    try:
        return pd.read_parquet(path, columns=columns)
    except Exception:
        return pd.read_parquet(path)


def _overlap_slice(t: np.ndarray, start: float, end: float) -> slice:
    return slice(int(np.searchsorted(t, start, "left")), int(np.searchsorted(t, end, "left")))


def _nanstat(fn, values: np.ndarray, default: float = 0.0) -> float:
    values = values[np.isfinite(values)]
    return float(fn(values)) if values.size else default


# ---------------------------------------------------------------- mouse
def mouse_window_features(t, x, y, et, ptype, dy, start: float) -> tuple[np.ndarray, float]:
    out = np.zeros(len(MOUSE_FEATURES), dtype=np.float32)
    move = (et == 0) & np.isfinite(x) & np.isfinite(y)
    tm, xm, ym = t[move], x[move], y[move]
    n_down, n_click = int((et == 1).sum()), int((et == 3).sum())
    wheel = (et == 4) | (et == 5)
    f = dict.fromkeys(MOUSE_FEATURES, 0.0)
    f["log_n_moves"] = math.log1p(len(tm))
    f["log_n_down"], f["log_n_click"] = math.log1p(n_down), math.log1p(n_click)
    f["log_n_wheel"] = math.log1p(int(wheel.sum()))
    f["log_wheel_mag"] = math.log1p(float(np.nansum(np.abs(dy[wheel])))) if wheel.any() else 0.0
    f["touch_frac"] = float(np.mean(ptype == 2)) if ptype.size else 0.0
    if len(tm) >= 2:
        dt = np.maximum(np.diff(tm), 1.0)
        d = np.hypot(np.diff(xm), np.diff(ym))
        cont = np.diff(tm) <= STROKE_GAP_MS
        v = d / dt
        vc = v[cont]
        f["log_path_px"] = math.log1p(float(d[cont].sum()))
        if vc.size:
            f["speed_med"], f["speed_std"] = float(np.median(vc)), float(np.std(vc))
            f["speed_p90"] = float(np.percentile(vc, 90))
            hist, _ = np.histogram(np.log1p(vc * 1000), bins=10, range=(0, 10))
            p = hist[hist > 0] / hist.sum()
            f["speed_entropy"] = float(-(p * np.log(p)).sum())
        if v.size >= 2:
            acc = np.abs(np.diff(v)) / dt[1:]
            f["accel_med"] = float(np.median(acc[cont[1:]])) if cont[1:].any() else 0.0
        seg = d > 0
        if seg.sum() >= 2:
            ang = np.arctan2(np.diff(ym), np.diff(xm))[seg]
            turn = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi)
            f["turn_med"] = float(np.median(turn))
        breaks = np.flatnonzero(~cont) + 1
        straight, lengths = [], []
        for idx in np.split(np.arange(len(tm)), breaks):
            if idx.size < 3:
                continue
            path = float(np.hypot(np.diff(xm[idx]), np.diff(ym[idx])).sum())
            if path <= 1.0:
                continue
            disp = math.hypot(xm[idx[-1]] - xm[idx[0]], ym[idx[-1]] - ym[idx[0]])
            straight.append(disp / path)
            lengths.append(path)
        f["log_n_strokes"] = math.log1p(len(lengths))
        if lengths:
            f["straightness_med"] = float(np.median(straight))
            f["log_stroke_len_med"] = math.log1p(float(np.median(lengths)))
    if t.size:
        bins = np.unique(((t - start) // 200).astype(int))
        f["idle_frac"] = 1.0 - min(len(bins), 50) / 50.0
        f["time_to_first_move"] = float((tm[0] - start) / WINDOW_MS) if len(tm) else 1.0
    else:
        f["idle_frac"], f["time_to_first_move"] = 1.0, 1.0
    downs, ups = t[et == 1], t[et == 2]
    if downs.size and ups.size:
        nxt = np.searchsorted(ups, downs, "left")
        ok = nxt < ups.size
        holds = ups[nxt[ok]] - downs[ok]
        holds = holds[(holds >= 0) & (holds < 3000)]
        f["hold_ms_med"] = float(np.median(holds)) / 1000.0 if holds.size else 0.0
    out[:] = [f[k] for k in MOUSE_FEATURES]
    valid = float(len(tm) >= 5 or n_click > 0 or wheel.sum() >= 3)
    return np.nan_to_num(out), valid


# ---------------------------------------------------------------- helpers per session
def _field_ids(context: dict[str, Any], key: str) -> dict[str, int]:
    mapping = context.get(key) or {}
    return {str(k): int(v) for k, v in mapping.items() if isinstance(v, (int, float))}


def _device(network: pd.DataFrame) -> dict[str, Any]:
    env_rows = network[network["type"] == "environment"] if "type" in network else network.iloc[:0]
    if env_rows.empty:
        return {}
    try:
        env = json.loads(env_rows["payload_json"].iloc[0]).get("env", {})
    except (TypeError, ValueError):
        return {}
    dev = {k: env.get(k) for k in DEVICE_KEYS}
    screen = env.get("screen") or {}
    dev["screen"] = f"{screen.get('width')}x{screen.get('height')}"
    return dev


def device_match(device: dict[str, Any], profile_device: dict[str, Any]) -> np.ndarray:
    known = bool(device) and bool(profile_device)
    vals = [float(known and device.get(k) is not None and device.get(k) == profile_device.get(k))
            for k in DEVICE_KEYS]
    return np.asarray(vals + [float(known)], dtype=np.float32)


def network_window_features(network: pd.DataFrame, starts: np.ndarray) -> np.ndarray:
    """Per-window RTT / request latency / HTTP error rate. Windows without pings fall back to the
    session median RTT (``rtt_in_window`` = 0 tells the model it is a fallback)."""
    out = np.zeros((len(starts), len(NETWORK_WINDOW_FEATURES)), np.float32)
    if network.empty or "type" not in network:
        return out
    t = pd.to_numeric(network["t_session_ms"], errors="coerce").to_numpy(float)
    ping = (network["type"] == "ping").to_numpy().copy()
    rtt = pd.to_numeric(network["rtt_ms"], errors="coerce").to_numpy(float)
    ping &= np.isfinite(rtt) & (rtt > 0) & (rtt < 60_000)
    req = (network["type"] == "server_request").to_numpy().copy()
    lat = pd.to_numeric(network.get("duration_ms"), errors="coerce").to_numpy(float) if "duration_ms" in network else np.full(len(t), np.nan)
    err = np.zeros(len(t), bool)
    for i in np.flatnonzero(req):
        try:
            err[i] = int((json.loads(network["payload_json"].iat[i]) or {}).get("status") or 0) >= 400
        except (TypeError, ValueError):
            pass
    sess_rtt = float(np.median(rtt[ping])) if ping.any() else 0.0
    sess_jit = float(np.mean(np.abs(np.diff(rtt[ping])))) if ping.sum() > 1 else 0.0
    for i, s in enumerate(starts):
        w = (t >= s) & (t < s + WINDOW_MS)
        r = rtt[w & ping]
        lw = lat[w & req]
        lw = lw[np.isfinite(lw) & (lw >= 0)]
        out[i] = [
            math.log1p(np.median(r) if r.size else sess_rtt),
            math.log1p(np.mean(np.abs(np.diff(r))) if r.size > 1 else sess_jit),
            math.log1p(np.median(lw)) if lw.size else 0.0,
            math.log1p(np.percentile(lw, 95)) if lw.size else 0.0,
            float(err[w & req].mean()) if (w & req).any() else 0.0,
            float(r.size > 0),
        ]
    return out


def build_session_windows(session_dir: Path, meta_row: dict[str, Any]) -> SessionWindows | None:
    context = json.loads((session_dir / "context.json").read_text()) if (session_dir / "context.json").exists() else {}
    meta = context.get("meta", {})
    kb_fields = _field_ids(context, "keyboard_fields")
    mouse_fields = _field_ids(context, "mouse_fields")
    kb_leaky = {kb_fields[f] for f in LEAKY_FIELDS if f in kb_fields}
    mouse_leaky = {mouse_fields[f] for f in LEAKY_FIELDS if f in mouse_fields}

    mouse = _read(session_dir / "mouse.parquet")
    if not mouse.empty:
        mouse = mouse[mouse["mask"].fillna(False).astype(bool) & mouse["t_session_ms"].notna()]
        mouse = mouse[~mouse["field_id"].isin(mouse_leaky)].sort_values("t_session_ms")
    kbw = _read(session_dir / "keyboard_windows.parquet")
    if not kbw.empty:
        kbw = kbw[kbw["embedding"].notna() & kbw["mask"].fillna(False).astype(bool)]
        kbw = kbw[~kbw["field_id"].isin(kb_leaky)]
    # pulse_windows.parquet has heart_rate_bpm=null everywhere; pulse.parquet carries the estimates.
    pulse = _read(session_dir / "pulse.parquet", ["t_session_ms", "heart_rate_bpm", "heart_rate_status",
                                                  "spectral_concentration", "face_crop_valid"])
    if not pulse.empty:
        pulse = pulse[pulse["heart_rate_status"].eq("estimate") & pulse["heart_rate_bpm"].notna()
                      & pulse["t_session_ms"].notna()].sort_values("t_session_ms")
    timeline = _read(session_dir / "timeline.parquet")
    frames = _read(session_dir / "frames.parquet", ["t_session_ms", "face_detected", "face_bbox_pixels", "width"])
    markers = _read(session_dir / "markers.parquet", ["type", "payload_json", "t_session_ms"])
    network = _read(session_dir / "network.parquet", ["type", "payload_json", "t_session_ms", "rtt_ms", "duration_ms"])

    ends = [0.0]
    for df in (mouse, timeline, markers):
        if not df.empty and df["t_session_ms"].notna().any():
            ends.append(float(df["t_session_ms"].max()))
    if not kbw.empty:
        ends.append(float(kbw["end_t_session_ms"].max()))
    duration = max(ends)
    if duration < WINDOW_MS / 2:
        return None
    starts = np.arange(0.0, max(duration - WINDOW_MS / 2, 0.0) + 1.0, STRIDE_MS)
    n = len(starts)

    kb = np.zeros((n, KB_DIM), np.float32)
    kb_mask = np.zeros(n, np.float32)
    kb_windows = []
    for _, r in kbw.iterrows():
        emb = np.asarray(r["embedding"], np.float32).reshape(-1)[:KB_DIM]
        if emb.size == KB_DIM and np.isfinite(emb).all() and np.linalg.norm(emb) > 0:
            kb_windows.append((float(r["start_t_session_ms"]), float(r["end_t_session_ms"]),
                               float(r["valid_length"]), emb / np.linalg.norm(emb)))

    mf = np.zeros((n, len(MOUSE_FEATURES)), np.float32)
    mm = np.zeros(n, np.float32)
    if not mouse.empty:
        cols = {c: pd.to_numeric(mouse[c], errors="coerce").to_numpy(np.float64)
                for c in ("t_session_ms", "x", "y", "event_type_id", "pointer_type_id", "delta_y")}
        t = cols["t_session_ms"]
        for i, s in enumerate(starts):
            sl = _overlap_slice(t, s, s + WINDOW_MS)
            mf[i], mm[i] = mouse_window_features(t[sl], cols["x"][sl], cols["y"][sl], cols["event_type_id"][sl],
                                                 cols["pointer_type_id"][sl], cols["delta_y"][sl], s)

    pf = np.zeros((n, len(PULSE_FEATURES)), np.float32)
    pm = np.zeros(n, np.float32)
    if not pulse.empty:
        pt = pulse["t_session_ms"].to_numpy(float)
        bpm = pd.to_numeric(pulse["heart_rate_bpm"], errors="coerce").to_numpy(float)
        sc = pd.to_numeric(pulse["spectral_concentration"], errors="coerce").to_numpy(float)
        crop = pulse["face_crop_valid"].fillna(False).astype(bool).to_numpy()
        for i, s in enumerate(starts):
            sl = _overlap_slice(pt, s, s + WINDOW_MS)
            b = bpm[sl]
            ok = np.isfinite(b)
            # ~30 Hz samples; require at least ~3 s of estimates inside the window.
            if ok.sum() >= 90:
                b = b[ok]
                q = max(len(b) // 4, 1)
                pf[i] = [b.mean() / 100.0, b.std() / 10.0, (b[-q:].mean() - b[:q].mean()) / 10.0,
                         _nanstat(np.mean, sc[sl]), float(crop[sl].mean()), math.log1p(ok.sum()) / 6.0]
                pm[i] = 1.0

    ff = np.zeros((n, len(FACE_FEATURES)), np.float32)
    fm = np.zeros(n, np.float32)
    if not timeline.empty and f"face_{BLENDSHAPES[0]}" in timeline:
        tt = timeline["t_session_ms"].to_numpy(float)
        order = np.argsort(tt)
        tt = tt[order]
        tl = timeline.iloc[order]

        def series(name: str, valid: str) -> np.ndarray:
            v = pd.to_numeric(tl[name], errors="coerce").to_numpy(float)
            if valid in tl:
                v = np.where(tl[valid].fillna(False).astype(bool).to_numpy(), v, np.nan)
            return v

        blend = np.stack([series(f"face_{b}", f"face_{b}_valid") for b in BLENDSHAPES], 1)
        post = np.stack([series(f"posture_{p}", f"posture_{p}_valid") if f"posture_{p}" in tl
                         else np.full(len(tl), np.nan) for p in POSTURE], 1)
        ft = frames["t_session_ms"].to_numpy(float) if not frames.empty else np.zeros(0)
        if ft.size:
            fo = np.argsort(ft)
            ft = ft[fo]
            boxes = frames["face_bbox_pixels"].iloc[fo]
            det = frames["face_detected"].iloc[fo].fillna(False).astype(bool).to_numpy()
            bb = np.full((len(ft), 4), np.nan)
            for j, (box, ok) in enumerate(zip(boxes, det)):
                if ok and box is not None and len(box) == 4:
                    bb[j] = np.asarray(box, float)
            bw = np.maximum(bb[:, 2] - bb[:, 0], 1.0)
            cx, cy = (bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2
            width = pd.to_numeric(frames["width"].iloc[fo], errors="coerce").to_numpy(float)
        for i, s in enumerate(starts):
            sl = _overlap_slice(tt, s, s + WINDOW_MS)
            bl = blend[sl]
            valid_frac = float(np.isfinite(bl[:, 0]).mean()) if len(bl) else 0.0
            if valid_frac < 0.3:
                continue
            with np.errstate(all="ignore"):
                vec = list(np.nan_to_num(np.nanmean(bl, 0))) + list(np.nan_to_num(np.nanstd(bl, 0)))
                pp = post[sl]
                vec += list(np.nan_to_num(np.nanmean(pp, 0))) + list(np.nan_to_num(np.nanstd(pp, 0)))
                head = [0.0, 0.0, 0.0, 0.0]
                if ft.size:
                    fs = _overlap_slice(ft, s, s + WINDOW_MS)
                    x, y, w = cx[fs] / bw[fs], cy[fs] / bw[fs], bw[fs] / np.maximum(width[fs], 1.0)
                    ok = np.isfinite(x)
                    if ok.sum() >= 3:
                        head = [float(np.nanmean(np.hypot(np.diff(x[ok]), np.diff(y[ok])))),
                                float(np.nanstd(x[ok])), float(np.nanstd(y[ok])), float(np.nanstd(w[ok]))]
            ff[i] = np.nan_to_num(np.asarray(vec + head + [valid_frac], np.float32))
            fm[i] = 1.0

    cf = np.zeros((n, len(CONTEXT_WINDOW_FEATURES)), np.float32)
    if not markers.empty:
        mt = markers["t_session_ms"].to_numpy(float)
        mtype = markers["type"].astype(str).to_numpy()
        fields = []
        for p in markers["payload_json"]:
            try:
                fields.append((json.loads(p) or {}).get("field") if isinstance(p, str) else None)
            except ValueError:
                fields.append(None)
        fields = np.asarray(fields, dtype=object)
        hidden = np.asarray(['"hidden": true' in str(p) for p in markers["payload_json"]])
        for i, s in enumerate(starts):
            sel = (mt >= s) & (mt < s + WINDOW_MS) & ~np.isin(fields, list(LEAKY_FIELDS))
            ty = mtype[sel]
            row = [np.sum(ty == "paste"), np.sum(ty == "copy"), np.sum(ty == "cut"),
                   np.sum(ty == "window_blur"), np.sum((ty == "visibility") & hidden[sel]),
                   np.sum(ty == "field_focus")]
            inputs = fields[sel][ty == "input"]
            row += [np.isin(inputs, list(g)).sum() for g in FIELD_GROUPS.values()]
            cf[i, :N_MARKER_FEATURES] = np.log1p(np.asarray(row, np.float32))
    cf[:, N_MARKER_FEATURES:] = network_window_features(network, starts)

    split_ms = None
    if meta_row["condition"] == "calm_1":
        # Split so both halves get typing when possible: profile vs probe must not share data.
        mids = sorted((a + b) / 2 for a, b, _, _ in kb_windows)
        active = starts[(mm > 0) | (fm > 0)]
        if len(mids) >= 2:
            split_ms = float((mids[len(mids) // 2 - 1] + mids[len(mids) // 2]) / 2)
        elif active.size >= 2:
            split_ms = float(np.median(active))
    for i, s in enumerate(starts):
        acc, wsum = np.zeros(KB_DIM), 0.0
        for a, b, length, emb in kb_windows:
            if split_ms is not None and (((a + b) / 2 < split_ms) != (s < split_ms)):
                continue  # never mix enrolment keystrokes into a probe window (and vice versa)
            ov = min(b, s + WINDOW_MS) - max(a, s)
            if ov > 0:
                w = length * ov / max(b - a, 1.0)
                acc += w * emb
                wsum += w
        if wsum > 0 and np.linalg.norm(acc) > 0:
            kb[i], kb_mask[i] = acc / np.linalg.norm(acc), 1.0
    keep = (mm > 0) | (kb_mask > 0) | (fm > 0) | (pm > 0)
    return SessionWindows(
        session_id=meta_row["session_id"], participant=meta_row["participant_code"],
        condition=meta_row["condition"], victim=meta.get("victim_code"),
        starts=starts[keep], kb=kb[keep], kb_mask=kb_mask[keep], mouse=mf[keep], mouse_mask=mm[keep],
        pulse=pf[keep], pulse_mask=pm[keep], face=ff[keep], face_mask=fm[keep], ctx=cf[keep],
        device=_device(network) if not network.empty else {}, split_ms=split_ms, kb_windows=kb_windows,
    )


# ---------------------------------------------------------------- enrolment / probe split and profiles
def enrol_mask(sw: SessionWindows) -> np.ndarray:
    """Calm windows wholly before the split build the profile; everything else is a probe."""
    if sw.condition != "calm_1" or sw.split_ms is None:
        return np.zeros(len(sw.starts), bool)
    return sw.starts + WINDOW_MS <= sw.split_ms


def probe_mask(sw: SessionWindows) -> np.ndarray:
    if sw.condition != "calm_1":
        return np.ones(len(sw.starts), bool)
    if sw.split_ms is None:
        return np.zeros(len(sw.starts), bool)
    return sw.starts >= sw.split_ms


def _masked_mean(x: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, float]:
    sel = m > 0
    return (x[sel].mean(0).astype(np.float32), 1.0) if sel.any() else (np.zeros(x.shape[1], np.float32), 0.0)


def build_profile(sw: SessionWindows) -> Profile | None:
    enrol = enrol_mask(sw)
    if not enrol.any():
        return None
    kb_parts = [(length, emb) for a, b, length, emb in sw.kb_windows if (a + b) / 2 < sw.split_ms]
    if kb_parts:
        kb = np.sum([l * e for l, e in kb_parts], 0)
        kb, kb_mask = (kb / np.linalg.norm(kb)).astype(np.float32), 1.0
    else:
        kb, kb_mask = np.zeros(KB_DIM, np.float32), 0.0
    mouse, mm = _masked_mean(sw.mouse[enrol], sw.mouse_mask[enrol])
    pulse, pm = _masked_mean(sw.pulse[enrol], sw.pulse_mask[enrol])
    face, fm = _masked_mean(sw.face[enrol], sw.face_mask[enrol])
    return Profile(sw.participant, sw.session_id, kb, kb_mask, mouse, mm, pulse, pm, face, fm, sw.device)


# ---------------------------------------------------------------- cache
def _fingerprint(processed_root: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(__file__).read_bytes())
    table = processed_root / "sessions.parquet"
    h.update(str(table.stat().st_mtime_ns).encode())
    return h.hexdigest()[:16]


def load_index(processed_root: Path = PROCESSED_ROOT) -> pd.DataFrame:
    df = pd.read_parquet(processed_root / "sessions.parquet")
    df = df[df["status"].eq("resumed") & df["condition"].isin(CONDITIONS)]
    return df[["session_id", "participant_code", "condition", "group", "output_directory"]].reset_index(drop=True)


def _session_dir(processed_root: Path, row: dict[str, Any]) -> Path:
    out = row.get("output_directory")
    if out and Path(out).is_dir():
        return Path(out)
    return processed_root / "sessions" / str(row["group"]) / str(row["session_id"])


def _build_one(args: tuple[str, dict[str, Any]]) -> SessionWindows | None:
    processed_root, row = args
    return build_session_windows(_session_dir(Path(processed_root), row), row)


def load_windows(processed_root: Path = PROCESSED_ROOT, cache_dir: Path | None = None,
                 workers: int = 16, rebuild: bool = False) -> dict[str, SessionWindows]:
    cache_dir = cache_dir or ROOT / "training" / "artifacts" / "fusion"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"windows_{_fingerprint(processed_root)}.pkl"
    if cache.exists() and not rebuild:
        return pickle.loads(cache.read_bytes())
    rows = load_index(processed_root).to_dict("records")
    jobs = [(str(processed_root), r) for r in rows]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as pool:
            built = list(pool.map(_build_one, jobs, chunksize=1))
    else:
        built = [_build_one(j) for j in jobs]
    sessions = {sw.session_id: sw for sw in built if sw is not None and len(sw.starts)}
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(sessions))
    tmp.replace(cache)
    return sessions
