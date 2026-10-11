"""Legacy session-level fusion (one vector per session). Superseded by ``training/fusion/``.

Label leaks (survey stress/hurry, condition, group, meta) were removed from the feature vectors and
the keyboard profile is now leave-one-out; results from models trained before that fix are invalid.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_ROOT = ROOT / "data" / "processed"
SESSION_TABLE = PROCESSED_ROOT / "sessions.parquet"
MODALITY_NAMES = ["keyboard", "mouse", "pulse", "face", "context", "profile"]
ALLOWED_CONDITIONS = {"calm_1", "calm_2", "calm_3", "dictation", "scam", "intruder"}
CALM_CONDITIONS = {"calm_1", "calm_2", "calm_3"}


def _sanitize_vector(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float64)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.clip(arr, -1e6, 1e6)
    return arr.astype(np.float32, copy=False)


def _to_float_array(values: Any, length: int | None = None) -> np.ndarray:
    flat: list[float] = []

    def walk(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple, np.ndarray)):
            for child in value:
                walk(child)
        elif isinstance(value, (int, float, np.integer, np.floating)):
            num = float(value)
            if np.isfinite(num):
                flat.append(num)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return
            if np.isfinite(number):
                flat.append(number)

    walk(values)
    arr = _sanitize_vector(flat)
    if arr.size == 0:
        arr = np.zeros(0, dtype=np.float32)
    if length is not None:
        if arr.size >= length:
            arr = arr[:length]
        else:
            pad = np.zeros(length - arr.size, dtype=np.float32)
            arr = np.concatenate([arr, pad])
    return arr


def _safe_1d_vector(value: Any, dim: int = 128) -> np.ndarray:
    vec = _sanitize_vector(_to_float_array(value, dim))
    if vec.size == 0:
        vec = np.zeros(dim, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0 and np.isfinite(norm):
        vec = vec / norm
    return vec[:dim]


@dataclass
class SessionRecord:
    session_id: str
    participant_code: str
    condition: str
    group: str
    stress: float
    hurry: float
    owner: int
    pressure: int
    suspicious: int
    keyboard_vector: np.ndarray
    mouse_vector: np.ndarray
    pulse_vector: np.ndarray
    face_vector: np.ndarray
    context_vector: np.ndarray
    profile_vector: np.ndarray
    token_mask: np.ndarray


def _read_context_json(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _numeric_from_session(session_dir: Path, file_name: str) -> np.ndarray:
    path = session_dir / file_name
    if not path.exists():
        return np.zeros(128, dtype=np.float32)
    try:
        df = pd.read_parquet(path)
    except Exception:
        return np.zeros(128, dtype=np.float32)
    if df.empty:
        return np.zeros(128, dtype=np.float32)
    numeric = df.select_dtypes(include=[np.number]).copy()
    values = []
    for col in numeric.columns:
        if col.endswith("_valid") or col.endswith("_observed") or col.endswith("_extrapolated") or col.endswith("_interpolated"):
            continue
        col_values = pd.to_numeric(numeric[col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float32)
        if col_values.size:
            values.append(np.nan_to_num(col_values, nan=0.0, posinf=0.0, neginf=0.0).mean())
    if not values:
        return np.zeros(128, dtype=np.float32)
    vector = np.asarray(values, dtype=np.float32)
    if vector.size < 128:
        vector = np.pad(vector, (0, 128 - vector.size), constant_values=0.0)
    else:
        vector = vector[:128]
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector.astype(np.float32)


def _load_session_properties(session_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    context = _read_context_json(json.loads((session_dir / "context.json").read_text()) if (session_dir / "context.json").exists() else {})
    mouse_summary = context.get("mouse_summary", {}) if isinstance(context, dict) else {}
    keyboard_summary = context.get("keyboard_summary", {}) if isinstance(context, dict) else {}
    survey = context.get("survey", {}) if isinstance(context, dict) else {}

    mouse_vec = _safe_1d_vector(mouse_summary, 128)
    pulse_vec = _numeric_from_session(session_dir, "pulse_windows.parquet")
    if np.allclose(pulse_vec, 0.0):
        pulse_vec = _safe_1d_vector({
            "heart_rate_bpm": _to_float_array({"value": 0.0}),
            "spectral_concentration": 0.0,
            "valid_face_fraction": 0.0,
            "pulse_valid": 0.0,
        }, 128)
    face_vec = _numeric_from_session(session_dir, "timeline.parquet")
    # No survey (filled in after the session) and no condition/order: those are labels, not inputs.
    context_vec = _safe_1d_vector({
        "keyboard_summary": keyboard_summary,
        "mouse_summary": mouse_summary,
    }, 128)
    return mouse_vec, pulse_vec, face_vec, context_vec, _safe_1d_vector(keyboard_summary, 128)


def build_session_records(processed_root: Path = PROCESSED_ROOT) -> list[SessionRecord]:
    table_path = processed_root / "sessions.parquet"
    if not table_path.exists():
        raise FileNotFoundError(f"Missing session summary table: {table_path}")

    df = pd.read_parquet(table_path)
    df = df[df["status"].fillna("").eq("resumed")].copy()
    df = df[df["condition"].isin(ALLOWED_CONDITIONS)].copy()

    profile_map: dict[str, np.ndarray] = defaultdict(list)
    valid_rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        session_id = str(row["session_id"])
        group = str(row["group"] or "unknown")
        condition = str(row["condition"])
        participant = str(row["participant_code"])
        stress = float(row["stress"] if pd.notna(row["stress"]) else 0.0)
        hurry = float(row["hurry"] if pd.notna(row["hurry"]) else 0.0)

        context = _read_context_json(row.get("context_json"))
        keyboard_embedding = row.get("keyboard_embedding")
        keyboard_vec = _sanitize_vector(np.asarray(keyboard_embedding, dtype=np.float32).reshape(-1))
        if keyboard_vec.size == 0:
            keyboard_vec = np.zeros(128, dtype=np.float32)
        if keyboard_vec.size < 128:
            keyboard_vec = np.pad(keyboard_vec, (0, 128 - keyboard_vec.size), constant_values=0.0)
        keyboard_vec = keyboard_vec[:128].astype(np.float32)
        norm = np.linalg.norm(keyboard_vec)
        if norm > 0 and np.isfinite(norm):
            keyboard_vec = keyboard_vec / norm

        if condition in CALM_CONDITIONS and keyboard_vec.any():
            profile_map[participant].append((session_id, keyboard_vec))

        valid_rows.append({
            "session_id": session_id,
            "participant_code": participant,
            "condition": condition,
            "group": group,
            "stress": stress,
            "hurry": hurry,
            "keyboard_vector": keyboard_vec,
            "context": context,
            "session_dir": processed_root / "sessions" / group / session_id,
        })

    records: list[SessionRecord] = []
    for item in valid_rows:
        participant = item["participant_code"]
        # Leave-one-out: a calm session must not be compared against a profile built from itself.
        calm_vectors = [v for sid, v in profile_map.get(participant, []) if sid != item["session_id"]]
        if calm_vectors:
            profile = np.mean(np.stack(calm_vectors, axis=0), axis=0)
            norm = np.linalg.norm(profile)
            if norm > 0 and np.isfinite(norm):
                profile = profile / norm
        else:
            profile = np.zeros(128, dtype=np.float32)

        context = item["context"]
        mouse_summary = context.get("mouse_summary", {}) if isinstance(context, dict) else {}
        mouse_vec = _safe_1d_vector(mouse_summary, 128)
        pulse_vec = _numeric_from_session(item["session_dir"], "pulse_windows.parquet")
        face_vec = _numeric_from_session(item["session_dir"], "timeline.parquet")
        context_vec = _safe_1d_vector({"mouse_summary": mouse_summary}, 128)

        condition = item["condition"]
        owner = int(condition in {"calm_1", "calm_2", "calm_3", "dictation"})
        pressure = int(condition == "scam")
        suspicious = int(condition in {"scam", "intruder"})

        mask = np.array([
            int(np.linalg.norm(item["keyboard_vector"]) > 0),
            int(np.linalg.norm(mouse_vec) > 0),
            int(np.linalg.norm(pulse_vec) > 0),
            int(np.linalg.norm(face_vec) > 0),
            int(np.linalg.norm(context_vec) > 0),
            int(np.linalg.norm(profile) > 0),
        ], dtype=np.float32)

        records.append(SessionRecord(
            session_id=item["session_id"],
            participant_code=participant,
            condition=condition,
            group=item["group"],
            stress=item["stress"],
            hurry=item["hurry"],
            owner=owner,
            pressure=pressure,
            suspicious=suspicious,
            keyboard_vector=item["keyboard_vector"],
            mouse_vector=mouse_vec,
            pulse_vector=pulse_vec,
            face_vector=face_vec,
            context_vector=context_vec,
            profile_vector=profile,
            token_mask=mask,
        ))

    return records


def make_person_split(records: list[SessionRecord]) -> dict[str, set[str]]:
    participants = sorted({record.participant_code for record in records})
    rng = np.random.default_rng(42)
    participants = list(rng.permutation(participants))
    train_count = 25 if len(participants) >= 25 else max(1, len(participants) // 2)
    val_count = 8 if len(participants) >= 25 else max(1, (len(participants) - train_count) // 2)
    test_count = len(participants) - train_count - val_count
    if test_count <= 0:
        test_count = max(1, len(participants) - train_count)
    train_participants = set(participants[:train_count])
    val_participants = set(participants[train_count:train_count + val_count])
    test_participants = set(participants[train_count + val_count:train_count + val_count + test_count])
    return {"train": train_participants, "val": val_participants, "test": test_participants}


class SessionFusionDataset(Dataset):
    def __init__(self, records: list[SessionRecord], training: bool = False):
        self.records = records
        self.training = training

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        rec = self.records[idx]
        tokens = np.stack([
            rec.keyboard_vector,
            rec.mouse_vector,
            rec.pulse_vector,
            rec.face_vector,
            rec.context_vector,
            rec.profile_vector,
        ], axis=0).astype(np.float32)

        mask = rec.token_mask.astype(np.float32)
        if self.training:
            if np.random.rand() < 0.2:
                tokens[2] = 0.0
                mask[2] = 0.0
            if np.random.rand() < 0.2:
                tokens[3] = 0.0
                mask[3] = 0.0

        return {
            "tokens": torch.from_numpy(tokens),
            "mask": torch.from_numpy(mask),
            "owner": torch.tensor(float(rec.owner), dtype=torch.float32),
            "pressure": torch.tensor(float(rec.pressure), dtype=torch.float32),
            "suspicious": torch.tensor(float(rec.suspicious), dtype=torch.float32),
            "participant_code": rec.participant_code,
            "session_id": rec.session_id,
        }


class ModalityMlp(nn.Module):
    def __init__(self, in_dim: int = 128, out_dim: int = 128):
        super().__init__()
        self.proj = nn.Sequential(
            nn.Linear(in_dim, out_dim),
            nn.ReLU(),
            nn.Linear(out_dim, out_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x)


class MiniFusionTransformer(nn.Module):
    def __init__(self, dim: int = 128, heads: int = 4, layers: int = 3):
        super().__init__()
        self.keyboard_proj = nn.Identity()
        self.mouse_proj = ModalityMlp(128, dim)
        self.pulse_proj = ModalityMlp(128, dim)
        self.face_proj = ModalityMlp(128, dim)
        self.context_proj = ModalityMlp(128, dim)
        self.profile_proj = nn.Identity()
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim, dtype=torch.float32))
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=dim,
            nhead=heads,
            dim_feedforward=512,
            dropout=0.15,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=layers)
        self.owner_head = nn.Linear(dim, 1)
        self.pressure_head = nn.Linear(dim, 1)
        self.suspicious_head = nn.Linear(dim, 1)

    def forward(self, tokens: torch.Tensor, mask: torch.Tensor) -> dict[str, torch.Tensor]:
        bsz = tokens.shape[0]
        keyboard = self.keyboard_proj(tokens[:, 0])
        mouse = self.mouse_proj(tokens[:, 1])
        pulse = self.pulse_proj(tokens[:, 2])
        face = self.face_proj(tokens[:, 3])
        context = self.context_proj(tokens[:, 4])
        profile = self.profile_proj(tokens[:, 5])

        token_sequence = torch.stack([keyboard, mouse, pulse, face, context, profile], dim=1)
        token_sequence = token_sequence * mask.unsqueeze(-1)
        cls = self.cls_token.expand(bsz, -1, -1)
        x = torch.cat([cls, token_sequence], dim=1)
        x = self.encoder(x)
        cls_out = x[:, 0]
        return {
            "owner": self.owner_head(cls_out).squeeze(-1),
            "pressure": self.pressure_head(cls_out).squeeze(-1),
            "suspicious": self.suspicious_head(cls_out).squeeze(-1),
        }


class LateFusionMLP(nn.Module):
    def __init__(self, in_dim: int = 128, hidden_dim: int = 64):
        super().__init__()
        self.modality_blocks = nn.ModuleList([
            nn.Sequential(
                nn.Linear(in_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
            )
            for _ in range(6)
        ])
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 6, hidden_dim * 4),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim * 4, hidden_dim),
            nn.ReLU(),
        )
        self.owner_head = nn.Linear(hidden_dim, 1)
        self.pressure_head = nn.Linear(hidden_dim, 1)
        self.suspicious_head = nn.Linear(hidden_dim, 1)

    def forward(self, tokens: torch.Tensor, mask: torch.Tensor) -> dict[str, torch.Tensor]:
        encoded = []
        for i in range(tokens.shape[1]):
            emb = self.modality_blocks[i](tokens[:, i])
            emb = emb * mask[:, i].unsqueeze(-1)
            encoded.append(emb)

        fused = torch.cat(encoded, dim=1)
        pooled = self.classifier(fused)
        return {
            "owner": self.owner_head(pooled).squeeze(-1),
            "pressure": self.pressure_head(pooled).squeeze(-1),
            "suspicious": self.suspicious_head(pooled).squeeze(-1),
        }


class LNNSequenceModel(nn.Module):
    def __init__(self, input_dim: int = 128, seq_len: int = 6, hidden_dim: int = 128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(seq_len * input_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(256, hidden_dim),
            nn.ReLU(),
        )
        self.owner_head = nn.Linear(hidden_dim, 1)
        self.pressure_head = nn.Linear(hidden_dim, 1)
        self.suspicious_head = nn.Linear(hidden_dim, 1)

    def forward(self, tokens: torch.Tensor, mask: torch.Tensor) -> dict[str, torch.Tensor]:
        x = tokens * mask.unsqueeze(-1)
        x = x.reshape(x.size(0), -1)
        x = self.net(x)
        return {
            "owner": self.owner_head(x).squeeze(-1),
            "pressure": self.pressure_head(x).squeeze(-1),
            "suspicious": self.suspicious_head(x).squeeze(-1),
        }


class SequenceRNNModel(nn.Module):
    def __init__(self, rnn_type: str = "lstm", hidden_dim: int = 64, layers: int = 2):
        super().__init__()
        if rnn_type not in {"lstm", "gru"}:
            raise ValueError("rnn_type must be 'lstm' or 'gru'")
        self.rnn_type = rnn_type
        rnn_cls = nn.LSTM if rnn_type == "lstm" else nn.GRU
        self.rnn = rnn_cls(
            input_size=128,
            hidden_size=hidden_dim,
            num_layers=layers,
            batch_first=True,
            dropout=0.1 if layers > 1 else 0.0,
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
        )
        self.owner_head = nn.Linear(hidden_dim // 2, 1)
        self.pressure_head = nn.Linear(hidden_dim // 2, 1)
        self.suspicious_head = nn.Linear(hidden_dim // 2, 1)

    def forward(self, tokens: torch.Tensor, mask: torch.Tensor) -> dict[str, torch.Tensor]:
        x = tokens * mask.unsqueeze(-1)
        out, _ = self.rnn(x)
        last = out[:, -1]
        fused = self.head(last)
        return {
            "owner": self.owner_head(fused).squeeze(-1),
            "pressure": self.pressure_head(fused).squeeze(-1),
            "suspicious": self.suspicious_head(fused).squeeze(-1),
        }


def _bce_loss(logits: torch.Tensor, targets: torch.Tensor, pos_weight: float | None = None) -> torch.Tensor:
    if pos_weight is None:
        return nn.functional.binary_cross_entropy_with_logits(logits, targets)
    return nn.functional.binary_cross_entropy_with_logits(logits, targets, pos_weight=torch.full_like(logits, pos_weight))


def _metrics_from_logits(logits: torch.Tensor, targets: torch.Tensor) -> dict[str, float]:
    probs = np.nan_to_num(torch.sigmoid(logits).detach().cpu().numpy(), nan=0.5, posinf=1.0, neginf=0.0)
    y = np.asarray(targets.detach().cpu().numpy(), dtype=np.float32)
    pred = (probs >= 0.5).astype(int)
    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(y, pred)) if y.size else 0.0,
        "precision": float(precision_score(y, pred, zero_division=0)) if y.size else 0.0,
        "recall": float(recall_score(y, pred, zero_division=0)) if y.size else 0.0,
        "f1": float(f1_score(y, pred, zero_division=0)) if y.size else 0.0,
        "auprc": float(average_precision_score(y, probs)) if np.unique(y).size >= 2 else 0.0,
        "roc_auc": float(roc_auc_score(y, probs)) if np.unique(y).size >= 2 else 0.0,
    }
    return metrics


def train_fusion_model(records: list[SessionRecord], device: str | None = None, epochs: int = 40) -> tuple[MiniFusionTransformer, dict[str, Any]]:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    split = make_person_split(records)
    train_records = [r for r in records if r.participant_code in split["train"]]
    val_records = [r for r in records if r.participant_code in split["val"]]
    test_records = [r for r in records if r.participant_code in split["test"]]

    train_ds = SessionFusionDataset(train_records, training=True)
    val_ds = SessionFusionDataset(val_records, training=False)
    test_ds = SessionFusionDataset(test_records, training=False)

    train_loader = DataLoader(train_ds, batch_size=12, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=32, shuffle=False)

    model = MiniFusionTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=7e-4, weight_decay=1e-4)

    pos_weights = {
        "owner": max(1.0, (len(train_records) - sum(r.owner for r in train_records)) / max(sum(r.owner for r in train_records), 1)),
        "pressure": max(1.0, (len(train_records) - sum(r.pressure for r in train_records)) / max(sum(r.pressure for r in train_records), 1)),
        "suspicious": max(1.0, (len(train_records) - sum(r.suspicious for r in train_records)) / max(sum(r.suspicious for r in train_records), 1)),
    }

    best_state: dict[str, Any] | None = None
    best_val = -1.0
    history: list[dict[str, Any]] = []

    for epoch in range(epochs):
        model.train()
        train_losses: list[float] = []
        for batch in train_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            owner_targets = batch["owner"].to(device)
            pressure_targets = batch["pressure"].to(device)
            suspicious_targets = batch["suspicious"].to(device)

            optimizer.zero_grad()
            logits = model(tokens, mask)
            loss = (
                0.5 * _bce_loss(logits["owner"], owner_targets, pos_weights["owner"])
                + 0.3 * _bce_loss(logits["suspicious"], suspicious_targets, pos_weights["suspicious"])
                + 0.2 * _bce_loss(logits["pressure"], pressure_targets, pos_weights["pressure"])
            )
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        model.eval()
        with torch.no_grad():
            val_logits = {"owner": [], "pressure": [], "suspicious": []}
            val_targets = {"owner": [], "pressure": [], "suspicious": []}
            for batch in val_loader:
                tokens = batch["tokens"].to(device)
                mask = batch["mask"].to(device)
                logits = model(tokens, mask)
                for key in val_logits:
                    val_logits[key].append(logits[key].cpu())
                    val_targets[key].append(batch[key].cpu())

            val_metric = 0.0
            for key in ["owner", "pressure", "suspicious"]:
                probs = torch.sigmoid(torch.cat(val_logits[key]))
                labels = torch.cat(val_targets[key])
                if labels.unique().numel() >= 2:
                    val_metric_key = roc_auc_score(labels.numpy(), probs.numpy())
                    val_metric = max(val_metric, float(val_metric_key))
                else:
                    val_metric_key = 0.0
                history.append({"epoch": epoch + 1, "train_loss": float(np.mean(train_losses)), "target": key, "val_auc": val_metric_key})
            if val_metric > best_val:
                best_val = float(val_metric)
                best_state = {k: v.detach().clone().cpu() for k, v in model.state_dict().items()}
            print(f"epoch={epoch+1:02d} train_loss={float(np.mean(train_losses)):.4f} val_auc={val_metric:.4f}")

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        test_logits = {"owner": [], "pressure": [], "suspicious": []}
        test_targets = {"owner": [], "pressure": [], "suspicious": []}
        for batch in test_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            logits = model(tokens, mask)
            for key in test_logits:
                test_logits[key].append(logits[key].cpu())
                test_targets[key].append(batch[key].cpu())

        summary = {
            "train_participants": sorted(split["train"]),
            "val_participants": sorted(split["val"]),
            "test_participants": sorted(split["test"]),
            "metrics": {
                key: _metrics_from_logits(torch.cat(test_logits[key]), torch.cat(test_targets[key]))
                for key in ["owner", "pressure", "suspicious"]
            },
        }

    return model, {"history": history, "split": split, "train_size": len(train_records), "val_size": len(val_records), "test_size": len(test_records), "metrics": summary["metrics"]}


def train_late_fusion_model(records: list[SessionRecord], device: str | None = None, epochs: int = 40) -> tuple[LateFusionMLP, dict[str, Any]]:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    split = make_person_split(records)
    train_records = [r for r in records if r.participant_code in split["train"]]
    val_records = [r for r in records if r.participant_code in split["val"]]
    test_records = [r for r in records if r.participant_code in split["test"]]

    train_ds = SessionFusionDataset(train_records, training=True)
    val_ds = SessionFusionDataset(val_records, training=False)
    test_ds = SessionFusionDataset(test_records, training=False)

    train_loader = DataLoader(train_ds, batch_size=16, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=32, shuffle=False)

    model = LateFusionMLP().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=1e-4)

    pos_weights = {
        "owner": max(1.0, (len(train_records) - sum(r.owner for r in train_records)) / max(sum(r.owner for r in train_records), 1)),
        "pressure": max(1.0, (len(train_records) - sum(r.pressure for r in train_records)) / max(sum(r.pressure for r in train_records), 1)),
        "suspicious": max(1.0, (len(train_records) - sum(r.suspicious for r in train_records)) / max(sum(r.suspicious for r in train_records), 1)),
    }

    best_state = None
    best_val = -1.0
    history = []
    for epoch in range(epochs):
        model.train()
        train_losses = []
        for batch in train_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            optimizer.zero_grad()
            logits = model(tokens, mask)
            loss = (
                0.5 * _bce_loss(logits["owner"], batch["owner"].to(device), pos_weights["owner"])
                + 0.3 * _bce_loss(logits["suspicious"], batch["suspicious"].to(device), pos_weights["suspicious"])
                + 0.2 * _bce_loss(logits["pressure"], batch["pressure"].to(device), pos_weights["pressure"])
            )
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        model.eval()
        with torch.no_grad():
            val_logits = {"owner": [], "pressure": [], "suspicious": []}
            val_targets = {"owner": [], "pressure": [], "suspicious": []}
            for batch in val_loader:
                tokens = batch["tokens"].to(device)
                mask = batch["mask"].to(device)
                logits = model(tokens, mask)
                for key in val_logits:
                    val_logits[key].append(logits[key].cpu())
                    val_targets[key].append(batch[key].cpu())
            val_metric = 0.0
            for key in ["owner", "pressure", "suspicious"]:
                probs = torch.sigmoid(torch.cat(val_logits[key]))
                labels = torch.cat(val_targets[key])
                if labels.unique().numel() >= 2:
                    val_metric_key = roc_auc_score(labels.numpy(), probs.numpy())
                    val_metric = max(val_metric, float(val_metric_key))
                else:
                    val_metric_key = 0.0
                history.append({"epoch": epoch + 1, "target": key, "train_loss": float(np.mean(train_losses)), "val_auc": float(val_metric_key)})
            if val_metric > best_val:
                best_val = float(val_metric)
                best_state = {k: v.detach().clone().cpu() for k, v in model.state_dict().items()}
            print(f"epoch={epoch+1:02d} train_loss={float(np.mean(train_losses)):.4f} val_auc={val_metric:.4f}")

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        test_logits = {"owner": [], "pressure": [], "suspicious": []}
        test_targets = {"owner": [], "pressure": [], "suspicious": []}
        for batch in test_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            logits = model(tokens, mask)
            for key in test_logits:
                test_logits[key].append(logits[key].cpu())
                test_targets[key].append(batch[key].cpu())
        summary = {
            "train_participants": sorted(split["train"]),
            "val_participants": sorted(split["val"]),
            "test_participants": sorted(split["test"]),
            "metrics": {
                key: _metrics_from_logits(torch.cat(test_logits[key]), torch.cat(test_targets[key]))
                for key in ["owner", "pressure", "suspicious"]
            },
        }
    return model, {"history": history, "split": split, "train_size": len(train_records), "val_size": len(val_records), "test_size": len(test_records), "metrics": summary["metrics"]}


def run_training() -> dict[str, Any]:
    records = list(build_session_records(PROCESSED_ROOT))
    if not records:
        raise ValueError("No resumed session records were found in processed data.")
    model, summary = train_fusion_model(records)
    return {"records": records, "model": model, "summary": summary}


def train_seq_model(model_name: str, records: list[SessionRecord], device: str | None = None, epochs: int = 30) -> tuple[nn.Module, dict[str, Any]]:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    split = make_person_split(records)
    train_records = [r for r in records if r.participant_code in split["train"]]
    val_records = [r for r in records if r.participant_code in split["val"]]
    test_records = [r for r in records if r.participant_code in split["test"]]

    train_ds = SessionFusionDataset(train_records, training=True)
    val_ds = SessionFusionDataset(val_records, training=False)
    test_ds = SessionFusionDataset(test_records, training=False)

    train_loader = DataLoader(train_ds, batch_size=16, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=32, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=32, shuffle=False)

    if model_name == "lnn":
        model = LNNSequenceModel().to(device)
        lr = 5e-4
    elif model_name == "lstm":
        model = SequenceRNNModel(rnn_type="lstm").to(device)
        lr = 3e-4
    elif model_name == "gru":
        model = SequenceRNNModel(rnn_type="gru").to(device)
        lr = 3e-4
    else:
        raise ValueError(f"Unsupported model_name: {model_name}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    pos_weights = {
        "owner": max(1.0, (len(train_records) - sum(r.owner for r in train_records)) / max(sum(r.owner for r in train_records), 1)),
        "pressure": max(1.0, (len(train_records) - sum(r.pressure for r in train_records)) / max(sum(r.pressure for r in train_records), 1)),
        "suspicious": max(1.0, (len(train_records) - sum(r.suspicious for r in train_records)) / max(sum(r.suspicious for r in train_records), 1)),
    }

    best_state = None
    best_val = -1.0
    history = []
    for epoch in range(epochs):
        model.train()
        train_losses = []
        for batch in train_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            optimizer.zero_grad()
            logits = model(tokens, mask)
            loss = (
                0.5 * _bce_loss(logits["owner"], batch["owner"].to(device), pos_weights["owner"])
                + 0.3 * _bce_loss(logits["suspicious"], batch["suspicious"].to(device), pos_weights["suspicious"])
                + 0.2 * _bce_loss(logits["pressure"], batch["pressure"].to(device), pos_weights["pressure"])
            )
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.detach().cpu()))

        model.eval()
        with torch.no_grad():
            val_logits = {"owner": [], "pressure": [], "suspicious": []}
            val_targets = {"owner": [], "pressure": [], "suspicious": []}
            for batch in val_loader:
                tokens = batch["tokens"].to(device)
                mask = batch["mask"].to(device)
                logits = model(tokens, mask)
                for key in val_logits:
                    val_logits[key].append(logits[key].cpu())
                    val_targets[key].append(batch[key].cpu())
            val_metric = 0.0
            for key in ["owner", "pressure", "suspicious"]:
                probs = torch.sigmoid(torch.cat(val_logits[key]))
                labels = torch.cat(val_targets[key])
                if labels.unique().numel() >= 2:
                    val_metric_key = roc_auc_score(labels.numpy(), probs.numpy())
                    val_metric = max(val_metric, float(val_metric_key))
                else:
                    val_metric_key = 0.0
                history.append({"epoch": epoch + 1, "target": key, "train_loss": float(np.mean(train_losses)), "val_auc": float(val_metric_key)})
            if val_metric > best_val:
                best_val = float(val_metric)
                best_state = {k: v.detach().clone().cpu() for k, v in model.state_dict().items()}
            print(f"[{model_name}] epoch={epoch+1:02d} train_loss={float(np.mean(train_losses)):.4f} val_auc={val_metric:.4f}")

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        test_logits = {"owner": [], "pressure": [], "suspicious": []}
        test_targets = {"owner": [], "pressure": [], "suspicious": []}
        for batch in test_loader:
            tokens = batch["tokens"].to(device)
            mask = batch["mask"].to(device)
            logits = model(tokens, mask)
            for key in test_logits:
                test_logits[key].append(logits[key].cpu())
                test_targets[key].append(batch[key].cpu())
        summary = {
            "train_participants": sorted(split["train"]),
            "val_participants": sorted(split["val"]),
            "test_participants": sorted(split["test"]),
            "metrics": {
                key: _metrics_from_logits(torch.cat(test_logits[key]), torch.cat(test_targets[key]))
                for key in ["owner", "pressure", "suspicious"]
            },
        }
    return model, {"history": history, "split": split, "train_size": len(train_records), "val_size": len(val_records), "test_size": len(test_records), "metrics": summary["metrics"]}


def run_late_fusion_training() -> dict[str, Any]:
    records = list(build_session_records(PROCESSED_ROOT))
    if not records:
        raise ValueError("No resumed session records were found in processed data.")
    model, summary = train_late_fusion_model(records)
    return {"records": records, "model": model, "summary": summary}


def run_sequence_model_benchmark() -> dict[str, dict[str, Any]]:
    records = list(build_session_records(PROCESSED_ROOT))
    if not records:
        raise ValueError("No resumed session records were found in processed data.")
    results = {}
    for model_name in ["lnn", "lstm", "gru"]:
        _, result = train_seq_model(model_name, records, epochs=25)
        results[model_name] = result
    return results


if __name__ == "__main__":
    result = run_sequence_model_benchmark()
    print(json.dumps(result, indent=2, default=str))
