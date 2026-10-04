import { api, type Session } from "../../services/api";

type EventMetadata = {
  sequence: number;
  time_ms: number;
  type: string;
  stage: string;
  field: string;
  length?: number;
  x?: number;
  y?: number;
};
const page = crypto.randomUUID();
let sequence = 0;
let queue: EventMetadata[] = [];
let enabled = false;
let busy = false;
let timer: ReturnType<typeof setInterval> | undefined;
let removeListeners: (() => void) | undefined;
export function configureTelemetry(session?: Session) {
  enabled = !!session?.telemetry;
  if (!enabled) {
    queue = [];
    if (timer) clearInterval(timer);
    timer = undefined;
    removeListeners?.();
    removeListeners = undefined;
  } else if (!timer) {
    timer = setInterval(() => void flushTelemetry(), 750);
    const fields = new Set([
      "username",
      "password",
      "recipient",
      "number",
      "title",
      "amount",
    ]);
    const input = (event: Event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement) || !fields.has(target.id))
        return;
      const stage =
        target.id === "username" || target.id === "password"
          ? "login"
          : "transfer";
      if (event instanceof KeyboardEvent) {
        if (event.key === "Backspace" || event.key === "Delete")
          collect("correction", stage, target.id);
      } else collect("focus", stage, target.id);
    };
    let lastPointer = 0;
    const pointer = (event: PointerEvent) => {
      const now = performance.now();
      if (now - lastPointer < 200) return;
      const stage =
        location.pathname === "/login"
          ? "login"
          : location.pathname === "/app/transfers/new"
            ? "transfer"
            : null;
      if (!stage) return;
      lastPointer = now;
      if (queue.length >= 100) queue.shift();
      queue.push({
        sequence: sequence++,
        time_ms: now,
        type: "pointer",
        stage,
        field: "none",
        x: Math.max(0, Math.round(event.clientX)),
        y: Math.max(0, Math.round(event.clientY)),
      });
    };
    document.addEventListener("keydown", input);
    document.addEventListener("focusin", input);
    document.addEventListener("pointermove", pointer);
    removeListeners = () => {
      document.removeEventListener("keydown", input);
      document.removeEventListener("focusin", input);
      document.removeEventListener("pointermove", pointer);
    };
  }
}
export function collect(
  type: string,
  stage: "login" | "transfer",
  field: string,
  length?: number,
) {
  if (!enabled) return;
  if (queue.length >= 100) queue.shift();
  queue.push({
    sequence: sequence++,
    time_ms: performance.now(),
    type,
    stage,
    field,
    ...(length === undefined ? {} : { length }),
  });
}
export async function flushTelemetry() {
  if (busy || !enabled || !queue.length) return;
  busy = true;
  const batch = queue.splice(0, 100);
  try {
    await api("/telemetry/events", "POST", {
      page,
      page_anchor_ms: performance.timeOrigin,
      events: batch,
    });
  } catch {
    if (enabled) queue = [...batch, ...queue].slice(-100);
  } finally {
    busy = false;
  }
}
