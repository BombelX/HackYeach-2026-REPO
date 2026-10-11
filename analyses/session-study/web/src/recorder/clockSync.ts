import { api } from "../api";

export type ClockOffset = {
  offset_ms: number;
  rtt_ms: number;
  t_perf: number;
  t_epoch: number;
  server_epoch_ms: number;
};

export async function measureClock(): Promise<ClockOffset> {
  const t0 = performance.now();
  const epoch0 = Date.now();
  const res = await api.clock();
  const t1 = performance.now();
  const rtt = t1 - t0;
  const mid = epoch0 + rtt / 2;
  return {
    offset_ms: res.server_epoch_ms - mid,
    rtt_ms: rtt,
    t_perf: t0,
    t_epoch: epoch0,
    server_epoch_ms: res.server_epoch_ms,
  };
}

export function startClockSync(onSample: (s: ClockOffset) => void): () => void {
  let timer: number | null = null;
  const tick = async () => {
    try {
      onSample(await measureClock());
    } catch {
      /* ignore */
    }
    timer = window.setTimeout(tick, 30_000);
  };
  void tick();
  return () => {
    if (timer) window.clearTimeout(timer);
  };
}
