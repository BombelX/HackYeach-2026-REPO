"""Export collected sessions to Parquet tables for model training."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from storage import DATA_DIR, SESSIONS_DIR, connect


KEY_FACE = [
    10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 2,
    234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152,
    454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
    61, 291, 13, 14, 78, 308, 33, 263, 133, 362,
]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if not xs:
        return None
    return float(statistics.median(xs))


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if not xs:
        return None
    return float(statistics.fmean(xs))


def pos_pulse(rgb: list[tuple[float, float, float]], fps: float = 30.0) -> dict[str, Any]:
    """Wang et al. POS rPPG on a sequence of mean RGB samples."""
    if len(rgb) < fps * 4:
        return {"hr": None, "quality": 0.0}
    c = np.array(rgb, dtype=np.float64)
    c = c - np.mean(c, axis=0, keepdims=True)
    n = len(c)
    window = int(fps * 1.6)
    window = max(window, 16)
    h = np.zeros(n)
    for i in range(0, n - window):
        w = c[i : i + window]
        mean = np.mean(w, axis=0)
        mean[mean == 0] = 1e-6
        cn = w / mean
        s = np.dot(cn, np.array([[0, 1, -1], [-2, 1, 1]], dtype=np.float64).T)
        std0 = np.std(s[:, 0]) + 1e-8
        std1 = np.std(s[:, 1]) + 1e-8
        pos = s[:, 0] + (std0 / std1) * s[:, 1]
        pos = pos - np.mean(pos)
        h[i : i + window] += pos
    # Band-pass via FFT around 0.7–3 Hz (42–180 BPM)
    freqs = np.fft.rfftfreq(n, d=1.0 / fps)
    spec = np.fft.rfft(h - np.mean(h))
    mag = np.abs(spec)
    band = (freqs >= 0.7) & (freqs <= 3.0)
    if not np.any(band):
        return {"hr": None, "quality": 0.0}
    peak = freqs[band][np.argmax(mag[band])]
    hr = float(peak * 60.0)
    energy = float(np.sum(mag[band]) + 1e-8)
    peak_e = float(np.max(mag[band]))
    quality = float(min(1.0, peak_e / (energy / max(np.sum(band), 1))))
    return {"hr": hr, "quality": quality}


def categorize_events(events: list[dict[str, Any]]) -> dict[str, list]:
    stages: list[tuple[str, float, float]] = []
    open_stage: dict[str, float] = {}
    for e in events:
        t = e.get("t_perf") or e.get("payload", {}).get("t_perf") or 0
        et = e.get("type")
        payload = e.get("payload") or {}
        if et == "stage_start":
            open_stage[payload.get("stage", "unknown")] = t
        elif et == "stage_end":
            name = payload.get("stage", "unknown")
            stages.append((name, open_stage.get(name, t), t))
    if not stages:
        if events:
            t0 = events[0].get("t_perf", 0)
            t1 = events[-1].get("t_perf", t0)
            stages = [("whole", t0, t1)]
        else:
            stages = []
    return {"stages": stages, "events": events}


def features_for_window(events: list[dict[str, Any]], face: list[dict[str, Any]], t0: float, t1: float) -> dict[str, Any]:
    ev = [e for e in events if t0 <= (e.get("t_perf") or 0) <= t1]
    fc = [f for f in face if t0 <= (f.get("t_perf") or 0) <= t1]
    downs = [e for e in ev if e.get("type") == "keydown"]
    ups = [e for e in ev if e.get("type") == "keyup"]
    holds = []
    flights = []
    down_map: dict[str, float] = {}
    last_up = None
    backspaces = 0
    for e in ev:
        if e.get("type") == "keydown":
            code = (e.get("payload") or {}).get("code")
            down_map[code] = e.get("t_perf")
            if (e.get("payload") or {}).get("category") == "backspace":
                backspaces += 1
        elif e.get("type") == "keyup":
            code = (e.get("payload") or {}).get("code")
            t_down = down_map.pop(code, None)
            if t_down is not None:
                holds.append(e.get("t_perf") - t_down)
            if last_up is not None:
                flights.append(e.get("t_perf") - last_up)
            last_up = e.get("t_perf")
    pauses = [f for f in flights if f > 1000]
    pastes = [e for e in ev if e.get("type") in ("paste", "input") and (e.get("payload") or {}).get("inputType") == "insertFromPaste"]
    pastes += [e for e in ev if e.get("type") == "paste"]
    moves = [e for e in ev if e.get("type") == "pointermove"]
    speeds = []
    idle = 0.0
    last_pt = None
    path_len = 0.0
    net_dx = 0.0
    net_dy = 0.0
    for e in moves:
        samples = (e.get("payload") or {}).get("samples") or []
        for s in samples:
            x, y, t = s.get("x"), s.get("y"), s.get("t")
            if last_pt is not None and x is not None:
                dt = max((t - last_pt[2]) / 1000.0, 1e-4)
                dist = math.hypot(x - last_pt[0], y - last_pt[1])
                speeds.append(dist / dt)
                path_len += dist
                net_dx += x - last_pt[0]
                net_dy += y - last_pt[1]
                if dist < 1:
                    idle += dt
            last_pt = (x, y, t)
    clicks = [e for e in ev if e.get("type") in ("click", "pointerup")]
    submit = next((e for e in ev if (e.get("payload") or {}).get("field") in ("submit", "confirm", "transfer") and e.get("type") == "click"), None)
    first = ev[0]["t_perf"] if ev else t0
    time_to_submit = (submit["t_perf"] - first) if submit else None
    rgb = []
    mouth = []
    brow = []
    face_w = []
    yaw = []
    pitch = []
    for f in fc:
        r = f.get("rgb") or {}
        fh = r.get("forehead")
        if fh and len(fh) == 3:
            rgb.append(tuple(fh))
        bs = f.get("blendshapes") or {}
        if isinstance(bs, dict):
            mouth.append(bs.get("jawOpen") or bs.get("mouthOpen") or 0)
            brow.append((bs.get("browInnerUp") or 0) + (bs.get("browDownLeft") or 0))
        elif isinstance(bs, list) and len(bs) > 25:
            mouth.append(bs[25] if len(bs) > 25 else 0)
        pose = f.get("pose") or []
        if pose and len(pose) > 0:
            nose = pose[0]
            lsh = pose[11] if len(pose) > 11 else None
            rsh = pose[12] if len(pose) > 12 else None
            if lsh and rsh:
                face_w.append(abs((lsh.get("x") or 0) - (rsh.get("x") or 0)))
            if isinstance(nose, dict):
                yaw.append(nose.get("x") or 0)
                pitch.append(nose.get("y") or 0)
    hr = pos_pulse(rgb, fps=30.0) if rgb else {"hr": None, "quality": 0.0}
    n_keys = len(downs)
    duration_s = max((t1 - t0) / 1000.0, 1e-3)
    straightness = None
    if path_len > 1:
        straightness = math.hypot(net_dx, net_dy) / path_len
    account_inputs = [e for e in ev if (e.get("payload") or {}).get("field") == "nrb" and e.get("type") == "keydown"]
    chunks = 1
    last_t = None
    for e in account_inputs:
        if last_t is not None and e["t_perf"] - last_t > 800:
            chunks += 1
        last_t = e["t_perf"]
    mask = {
        "keyboard": n_keys > 0,
        "mouse": len(moves) > 0,
        "hr": hr["hr"] is not None,
        "posture": len(fc) > 0,
        "face": len(fc) > 0,
    }
    return {
        "n_events": len(ev),
        "n_face_frames": len(fc),
        "duration_s": duration_s,
        "key_count": n_keys,
        "key_rate": n_keys / duration_s,
        "hold_median_ms": _median(holds),
        "flight_median_ms": _median(flights),
        "pause_gt1s": len(pauses),
        "backspace_rate": backspaces / max(n_keys, 1),
        "paste_count": len(pastes),
        "nrb_chunks": chunks,
        "mouse_speed_median": _median(speeds),
        "mouse_idle_s": idle,
        "mouse_straightness": straightness,
        "time_to_submit_ms": time_to_submit,
        "click_count": len(clicks),
        "hr": hr["hr"],
        "hr_quality": hr["quality"],
        "mouth_open_mean": _mean(mouth),
        "brow_mean": _mean(brow),
        "shoulder_width_mean": _mean(face_w),
        "head_x_std": float(np.std(yaw)) if yaw else None,
        "head_y_std": float(np.std(pitch)) if pitch else None,
        "mask_keyboard": mask["keyboard"],
        "mask_mouse": mask["mouse"],
        "mask_hr": mask["hr"],
        "mask_posture": mask["posture"],
        "mask_face": mask["face"],
    }


def export_all(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    sessions = conn.execute(
        """SELECT s.*, p.code as participant_code, p.identity_json
           FROM sessions s JOIN participants p ON p.id = s.participant_id
           WHERE p.deleted_at IS NULL"""
    ).fetchall()
    conn.close()
    event_rows = []
    feat_rows = []
    for s in sessions:
        sid = s["id"]
        d = SESSIONS_DIR / sid
        events = _read_jsonl(d / "events.jsonl")
        face = _read_jsonl(d / "face.jsonl")
        meta = {}
        if (d / "meta.json").exists():
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        survey = {}
        if (d / "survey.json").exists():
            survey = json.loads((d / "survey.json").read_text(encoding="utf-8"))
        for e in events:
            event_rows.append(
                {
                    "session_id": sid,
                    "participant_code": s["participant_code"],
                    "condition": s["condition"],
                    "type": e.get("type"),
                    "t_perf": e.get("t_perf"),
                    "t_epoch": e.get("t_epoch"),
                    "payload": json.dumps(e.get("payload") or {}, ensure_ascii=False),
                }
            )
        grouped = categorize_events(events)
        if not grouped["stages"]:
            grouped["stages"] = [("whole", 0, 1)]
        for name, a, b in grouped["stages"]:
            feat = features_for_window(events, face, a, b)
            feat.update(
                {
                    "session_id": sid,
                    "participant_code": s["participant_code"],
                    "condition": s["condition"],
                    "stage": name,
                    "stress": survey.get("stress"),
                    "hurry": survey.get("hurry"),
                    "order_index": s["order_index"],
                    "consents": meta.get("consents"),
                }
            )
            feat_rows.append(feat)
        # also whole-session features
        if events:
            t0 = min(e.get("t_perf") or 0 for e in events)
            t1 = max(e.get("t_perf") or 0 for e in events)
            feat = features_for_window(events, face, t0, t1)
            feat.update(
                {
                    "session_id": sid,
                    "participant_code": s["participant_code"],
                    "condition": s["condition"],
                    "stage": "session",
                    "stress": survey.get("stress"),
                    "hurry": survey.get("hurry"),
                    "order_index": s["order_index"],
                }
            )
            feat_rows.append(feat)
    events_df = pd.DataFrame(event_rows)
    feats_df = pd.DataFrame(feat_rows)
    events_path = out_dir / "events.parquet"
    feats_path = out_dir / "features.parquet"
    events_df.to_parquet(events_path, index=False)
    feats_df.to_parquet(feats_path, index=False)
    print(f"Wrote {len(events_df)} events -> {events_path}")
    print(f"Wrote {len(feats_df)} feature rows -> {feats_path}")


def main():
    parser = argparse.ArgumentParser(description="Export Bank24 collector sessions to Parquet")
    parser.add_argument("--out", default=str(DATA_DIR / "export"), help="Output directory")
    args = parser.parse_args()
    export_all(Path(args.out))


if __name__ == "__main__":
    main()
