import os
import random
from collections import defaultdict
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, Dataset, Sampler
PATH = "/workspace/datasets/aalto-136m/keystrokes.npz"
CROP_LENGTHS = (16, 24, 32, 48, 64, 96)
MAX_LEN = 96
MIN_LEN = 16
D_MODEL = 128
EPOCHS = 60
USERS_PER_BATCH = 64
WINDOWS_PER_USER = 8




def seed_worker(worker_id):
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)
class KeystrokeWindows(Dataset):
    def __init__(self, path, max_len=MAX_LEN, min_len=MIN_LEN, training=False):
        pack = np.load(path)
        self.key_id = pack["key_id"]
        self.feats = pack["feats"]
        self.bounds = pack["bounds"]
        self.max_len = max_len
        self.min_len = min_len
        self.training = training
        self.index = []
        for start, end, user in self.bounds:
            n = int(end - start)
            if n < self.min_len:
                continue
            pos = int(start)
            while n > 0:
                take = min(self.max_len, n)
                if take >= self.min_len:
                    self.index.append((pos, take, int(user)))
                pos += take
                n -= take
    def __len__(self):
        return len(self.index)
    def __getitem__(self, i):
        pos, n, user = self.index[i]
        if self.training:
            choices = [L for L in CROP_LENGTHS if L <= n]
            take = random.choice(choices)
            offset = random.randint(0, n - take)
        else:
            take = n
            offset = 0
        src = pos + offset
        keys = np.zeros(self.max_len, np.int64)
        feats = np.zeros((self.max_len, 8), np.float32)
        mask = np.zeros(self.max_len, np.bool_)
        raw = self.key_id[src:src + take].astype(np.int64)
        keys[:take] = np.clip(raw, 0, 32767)
        feats[:take] = self.feats[src:src + take]
        mask[:take] = True
        return {
            "key_id": torch.from_numpy(keys),
            "feats": torch.from_numpy(feats),
            "mask": torch.from_numpy(mask),
            "user": user,
        }
class UserGroupedSampler(Sampler):
    """Każdy batch: 64 osoby × 8 okien. Inaczej w batchu nie ma par tej samej osoby i contrastive loss jest pusty."""
    def __init__(self, groups, users_per_batch, windows_per_user):
        self.groups = groups
        self.users = list(groups)
        self.users_per_batch = users_per_batch
        self.windows_per_user = windows_per_user
        self.epoch = 0
        usable = len(self.users) // users_per_batch
        self.n_batches = usable
    def set_epoch(self, epoch):
        self.epoch = epoch
    def __len__(self):
        return self.n_batches
    def __iter__(self):
        rng = random.Random(self.epoch + 10007)
        users = self.users[:]
        rng.shuffle(users)
        stop = self.n_batches * self.users_per_batch
        for i in range(0, stop, self.users_per_batch):
            batch = []
            for user in users[i:i + self.users_per_batch]:
                pool = self.groups[user]
                if len(pool) >= self.windows_per_user:
                    picked = rng.sample(pool, self.windows_per_user)
                else:
                    picked = [rng.choice(pool) for _ in range(self.windows_per_user)]
                batch.extend(picked)
            yield batch
class ConvModule(nn.Module):
    def __init__(self, d, kernel=31):
        super().__init__()
        self.norm = nn.LayerNorm(d)
        self.pw1 = nn.Conv1d(d, 2 * d, 1)
        self.dw = nn.Conv1d(d, d, kernel, padding=kernel // 2, groups=d)
        self.bn = nn.BatchNorm1d(d)
        self.pw2 = nn.Conv1d(d, d, 1)
        self.drop = nn.Dropout(0.1)
    def forward(self, x):
        h = self.norm(x).transpose(1, 2)
        h = F.glu(self.pw1(h), dim=1)
        h = F.silu(self.bn(self.dw(h)))
        h = self.drop(self.pw2(h))
        return h.transpose(1, 2)
class ConformerBlock(nn.Module):
    def __init__(self, d, heads):
        super().__init__()
        self.ff1 = nn.Sequential(
            nn.LayerNorm(d), nn.Linear(d, 4 * d), nn.SiLU(), nn.Dropout(0.1), nn.Linear(4 * d, d)
        )
        self.ff2 = nn.Sequential(
            nn.LayerNorm(d), nn.Linear(d, 4 * d), nn.SiLU(), nn.Dropout(0.1), nn.Linear(4 * d, d)
        )
        self.attn_norm = nn.LayerNorm(d)
        self.attn = nn.MultiheadAttention(d, heads, dropout=0.1, batch_first=True)
        self.conv = ConvModule(d)
        self.out_norm = nn.LayerNorm(d)
    def forward(self, x, pad):
        x = x + 0.5 * self.ff1(x)
        h = self.attn_norm(x)
        h, _ = self.attn(h, h, h, key_padding_mask=pad, need_weights=False)
        x = x + h
        x = x + self.conv(x)
        x = x + 0.5 * self.ff2(x)
        return self.out_norm(x)
class KeystrokeConformer(nn.Module):
    def __init__(self, d=D_MODEL, layers=4, heads=4):
        super().__init__()
        self.key = nn.Embedding(32768, d, padding_idx=0)
        self.feat = nn.Linear(8, d)
        self.blocks = nn.ModuleList(ConformerBlock(d, heads) for _ in range(layers))
        self.score = nn.Linear(d, 1)
        self.proj = nn.Linear(d, d)
    def forward(self, key_id, feats, mask):
        x = self.key(key_id) + self.feat(feats)
        x = x * mask.unsqueeze(-1)
        pad = ~mask
        for block in self.blocks:
            x = block(x, pad)
            x = x * mask.unsqueeze(-1)
        w = self.score(x).squeeze(-1).masked_fill(pad, -1e9)
        alpha = torch.softmax(w, dim=1).unsqueeze(-1)
        return self.proj((alpha * x).sum(dim=1))
def supcon(z, users, tau=0.1):
    z = F.normalize(z, dim=-1)
    sim = z @ z.T / tau
    eye = torch.eye(z.size(0), device=z.device, dtype=torch.bool)
    sim = sim.masked_fill(eye, -1e9)
    pos = (users[:, None] == users[None, :]) & ~eye
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    denom = pos.sum(dim=1).clamp(min=1)
    return -((log_prob * pos).sum(dim=1) / denom).mean()
def groups_for(ds, rank, world):
    buckets = defaultdict(list)
    for i, (_, _, user) in enumerate(ds.index):
        if user % 10 <= 1:
            continue
        if user % world == rank:
            buckets[user].append(i)
    return {u: v for u, v in buckets.items() if len(v) >= 2}




def main():
    dist.init_process_group(backend="nccl")
    rank = int(os.environ["LOCAL_RANK"])
    world = dist.get_world_size()
    torch.cuda.set_device(rank)
    ds = KeystrokeWindows(PATH, training=True)
    groups = groups_for(ds, rank, world)
    sampler = UserGroupedSampler(groups, USERS_PER_BATCH, WINDOWS_PER_USER)
    loader = DataLoader(
        ds,
        batch_sampler=sampler,
        num_workers=4,
        worker_init_fn=seed_worker,
        pin_memory=True,
        persistent_workers=True,
        prefetch_factor=4,
    )

    
    total_steps = EPOCHS * len(loader)
    warmup = max(1, int(0.05 * total_steps))
    hold = int(0.70 * total_steps)
    def lr_at(step):
        if step < warmup:
            return 3e-4 * (step + 1) / warmup
        if step < hold:
            return 3e-4
        t = (step - hold) / max(1, total_steps - hold)
        return 1e-5 + (3e-4 - 1e-5) * 0.5 * (1 + np.cos(np.pi * t))
    model = DDP(KeystrokeConformer().to(rank), device_ids=[rank])
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda step: lr_at(step) / 3e-4)
    for epoch in range(EPOCHS):
        sampler.set_epoch(epoch)
        model.train()
        total = 0.0
        seen = 0
        for batch in loader:
            key_id = batch["key_id"].to(rank, non_blocking=True)
            feats = batch["feats"].to(rank, non_blocking=True)
            mask = batch["mask"].to(rank, non_blocking=True)
            users = batch["user"].to(rank, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                loss = supcon(model(key_id, feats, mask), users)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            total += loss.item()
            seen += 1
        dist.barrier()
        if rank == 0:
            lr = opt.param_groups[0]["lr"]
            print(f"epoch {epoch} loss {total / max(seen, 1):.4f} lr {lr:.6e}", flush=True)
            torch.save(model.module.state_dict(), f"/workspace/keystroke_long_epoch_{epoch}.pt")
    dist.destroy_process_group()
if __name__ == "__main__":
    main()