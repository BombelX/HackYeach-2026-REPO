"""(session, profile) pairs, labels, normalisation and tensors for the fusion model."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from training.fusion.features import (
    CONTEXT_PAIR_FEATURES, CONTEXT_WINDOW_FEATURES, FACE_FEATURES, MOUSE_FEATURES, NET_EMB_DIM, PULSE_FEATURES,
    Profile, SessionWindows, build_profile, device_match, probe_mask,
)

MODALITIES = ("mouse", "pulse", "face", "ctx")
PROFILE_STATS_DIM = len(MOUSE_FEATURES) + len(PULSE_FEATURES) + len(FACE_FEATURES) + 4
INPUT_DIMS = dict(mouse_dim=len(MOUSE_FEATURES), pulse_dim=len(PULSE_FEATURES), face_dim=len(FACE_FEATURES),
                  ctx_dim=len(CONTEXT_WINDOW_FEATURES) + len(CONTEXT_PAIR_FEATURES), net_dim=NET_EMB_DIM,
                  profile_stats_dim=PROFILE_STATS_DIM)


@dataclass(frozen=True)
class Pair:
    session_id: str
    profile: str            # participant whose calm enrolment is the reference
    nonowner: int           # 1 = the person in the session is not the profile owner
    pressure: int           # 1 = owner acting under scam pressure
    pressure_valid: int     # pressure is only defined for owner pairs
    kind: str


def build_profiles(sessions: dict[str, SessionWindows]) -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for sw in sorted(sessions.values(), key=lambda s: s.session_id):
        if sw.condition == "calm_1" and sw.participant not in profiles:
            prof = build_profile(sw)
            if prof is not None:
                profiles[sw.participant] = prof
    return profiles


def make_pairs(sessions: dict[str, SessionWindows], profiles: dict[str, Profile],
               participants: set[str], impostors: bool = True) -> list[Pair]:
    """Owner pairs (calm probe half, dictation, scam vs own profile), intruder vs victim, and
    impostor pairs (any session of B vs profile of A). Both people must be in ``participants``
    so nobody crosses the train/val/test boundary. Intruder vs own profile is ambiguous and skipped."""
    pairs: list[Pair] = []
    owners = sorted(p for p in profiles if p in participants)
    for sw in sorted(sessions.values(), key=lambda s: s.session_id):
        p = sw.participant
        if p not in participants or not probe_mask(sw).any():
            continue
        if p in profiles:
            if sw.condition in ("calm_1", "dictation"):
                pairs.append(Pair(sw.session_id, p, 0, 0, 1, f"owner_{sw.condition}"))
            elif sw.condition == "scam":
                pairs.append(Pair(sw.session_id, p, 0, 1, 1, "owner_scam"))
        victim = sw.victim if sw.condition == "intruder" else None
        if victim and victim != p and victim in participants and victim in profiles:
            pairs.append(Pair(sw.session_id, victim, 1, 0, 0, "intruder_victim"))
        if impostors:
            for a in owners:
                if a != p and a != victim:
                    pairs.append(Pair(sw.session_id, a, 1, 0, 0, f"impostor_{sw.condition}"))
    return pairs


class Normalizer:
    def __init__(self, stats: dict[str, tuple[np.ndarray, np.ndarray]]):
        self.stats = stats

    @classmethod
    def fit(cls, sessions: list[SessionWindows]) -> "Normalizer":
        stats = {}
        for name in ("mouse", "pulse", "face", "ctx"):
            rows = []
            for sw in sessions:
                x = getattr(sw, name)
                m = np.ones(len(x), bool) if name == "ctx" else getattr(sw, f"{name}_mask") > 0
                rows.append(x[m])
            x = np.concatenate(rows) if rows else np.zeros((1, 1))
            mean, std = x.mean(0), x.std(0)
            stats[name] = (mean.astype(np.float32), np.where(std > 1e-6, std, 1.0).astype(np.float32))
        return cls(stats)

    def __call__(self, name: str, x: np.ndarray) -> np.ndarray:
        mean, std = self.stats[name]
        return np.clip((x - mean) / std, -8, 8).astype(np.float32)

    def state(self) -> dict[str, list[list[float]]]:
        return {k: [m.tolist(), s.tolist()] for k, (m, s) in self.stats.items()}

    @classmethod
    def from_state(cls, state: dict[str, list[list[float]]]) -> "Normalizer":
        return cls({k: (np.asarray(m, np.float32), np.asarray(s, np.float32)) for k, (m, s) in state.items()})


def pair_tensors(pairs: list[Pair], sessions: dict[str, SessionWindows], profiles: dict[str, Profile],
                 norm: Normalizer) -> dict[str, np.ndarray]:
    cols: dict[str, list[np.ndarray]] = {k: [] for k in (
        "kb", "mouse", "pulse", "face", "ctx", "net", "net_mask", "mask", "profile_kb", "profile_kb_mask", "profile_stats",
        "nonowner", "pressure", "pressure_valid", "pair", "weight")}
    for idx, pair in enumerate(pairs):
        sw, prof = sessions[pair.session_id], profiles[pair.profile]
        sel = probe_mask(sw)
        n = int(sel.sum())
        feats = {}
        for name in ("mouse", "pulse", "face"):
            x, m = norm(name, getattr(sw, name)[sel]), getattr(sw, f"{name}_mask")[sel]
            pm = getattr(prof, f"{name}_mask")
            ref = norm(name, getattr(prof, name)[None]) if pm else np.zeros((1, x.shape[1]), np.float32)
            feats[name] = np.concatenate([x, (x - ref) * pm], 1) * m[:, None]
            cols[name].append(feats[name])
        ctx = np.concatenate([norm("ctx", sw.ctx[sel]),
                              np.repeat(device_match(sw.device, prof.device)[None], n, 0)], 1)
        cols["ctx"].append(ctx)
        if sw.net_emb is not None and sw.net_mask is not None:
            nm = sw.net_mask[sel].astype(np.float32)
            cols["net"].append(sw.net_emb[sel].astype(np.float32) * nm[:, None])
            cols["net_mask"].append(nm)
        else:
            cols["net"].append(np.zeros((n, NET_EMB_DIM), np.float32))
            cols["net_mask"].append(np.zeros(n, np.float32))
        cols["kb"].append(sw.kb[sel] * sw.kb_mask[sel, None])
        any_prof = float(max(prof.kb_mask, prof.mouse_mask, prof.pulse_mask, prof.face_mask))
        cols["mask"].append(np.stack([sw.kb_mask[sel], sw.mouse_mask[sel], sw.pulse_mask[sel], sw.face_mask[sel],
                                      np.ones(n, np.float32), np.full(n, any_prof, np.float32)], 1))
        stats = np.concatenate([
            norm("mouse", prof.mouse) * prof.mouse_mask, norm("pulse", prof.pulse) * prof.pulse_mask,
            norm("face", prof.face) * prof.face_mask,
            [prof.mouse_mask, prof.pulse_mask, prof.face_mask, prof.kb_mask]]).astype(np.float32)
        cols["profile_kb"].append(np.repeat(prof.kb[None] * prof.kb_mask, n, 0))
        cols["profile_kb_mask"].append(np.full(n, prof.kb_mask, np.float32))
        cols["profile_stats"].append(np.repeat(stats[None], n, 0))
        for k in ("nonowner", "pressure", "pressure_valid"):
            cols[k].append(np.full(n, getattr(pair, k), np.float32))
        cols["pair"].append(np.full(n, idx, np.int64))
        cols["weight"].append(np.full(n, 1.0 / n, np.float32))
    return {k: np.concatenate(v).astype(np.int64 if k == "pair" else np.float32) for k, v in cols.items()}


def to_torch(arrays: dict[str, np.ndarray], device: str) -> dict[str, torch.Tensor]:
    return {k: torch.from_numpy(v).to(device) for k, v in arrays.items()}
