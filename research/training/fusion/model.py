"""Small fusion transformer: 6 modality tokens + CLS, 2 layers, 4 heads, d=128 (<1M params)."""
from __future__ import annotations

import torch
from torch import nn

TOKENS = ("keyboard", "mouse", "pulse", "face", "context", "profile")


def _mlp(in_dim: int, dim: int, hidden: int = 64, dropout: float = 0.1) -> nn.Sequential:
    return nn.Sequential(nn.LayerNorm(in_dim), nn.Linear(in_dim, hidden), nn.GELU(),
                         nn.Dropout(dropout), nn.Linear(hidden, dim))


class FusionTransformer(nn.Module):
    """Inputs are already-computed features; the keyboard Conformer stays frozen upstream.

    mouse/pulse/face inputs are ``[x, x - profile_x]`` (normalised), so each encoder sees both
    the window and its deviation from the owner's calm enrolment. The keyboard embedding and the
    keyboard part of the profile share one linear adapter so they stay in the same space and
    attention can compare them directly.
    """

    def __init__(self, mouse_dim: int, pulse_dim: int, face_dim: int, ctx_dim: int, profile_stats_dim: int,
                 net_dim: int = 64, dim: int = 128, heads: int = 4, layers: int = 2, ff: int = 256,
                 dropout: float = 0.1):
        super().__init__()
        self.kb_adapter = nn.Linear(128, dim)
        self.mouse = _mlp(2 * mouse_dim, dim)
        self.pulse = _mlp(2 * pulse_dim, dim, hidden=32)
        self.face = _mlp(2 * face_dim, dim)
        self.context = _mlp(ctx_dim, dim, hidden=32)
        # Network-model embedding is added into the context token (zero + mask when absent).
        self.net_adapter = nn.Linear(net_dim, dim)
        self.profile_stats = _mlp(profile_stats_dim, dim)
        self.type_emb = nn.Parameter(torch.randn(len(TOKENS) + 1, dim) * 0.02)
        self.cls = nn.Parameter(torch.zeros(1, 1, dim))
        layer = nn.TransformerEncoderLayer(dim, heads, ff, dropout, activation="gelu",
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(dim)
        self.nonowner_head = nn.Linear(dim, 1)
        self.pressure_head = nn.Linear(dim, 1)

    def forward(self, batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        kb_mask = batch["mask"][:, 0:1]
        profile = (self.kb_adapter(batch["profile_kb"]) * batch["profile_kb_mask"].unsqueeze(-1)
                   + self.profile_stats(batch["profile_stats"]))
        tokens = torch.stack([
            self.kb_adapter(batch["kb"]) * kb_mask,
            self.mouse(batch["mouse"]),
            self.pulse(batch["pulse"]),
            self.face(batch["face"]),
            self.context(batch["ctx"]) + self.net_adapter(batch["net"]) * batch["net_mask"].unsqueeze(-1),
            profile,
        ], dim=1)
        x = torch.cat([self.cls.expand(tokens.shape[0], -1, -1), tokens], 1) + self.type_emb
        # Missing modalities are masked out of attention (zero + mask, never imputed).
        pad = torch.cat([torch.zeros_like(batch["mask"][:, :1]), 1 - batch["mask"]], 1).bool()
        x = self.encoder(x, src_key_padding_mask=pad)
        cls = self.norm(x[:, 0])
        return {"nonowner": self.nonowner_head(cls).squeeze(-1), "pressure": self.pressure_head(cls).squeeze(-1)}


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
