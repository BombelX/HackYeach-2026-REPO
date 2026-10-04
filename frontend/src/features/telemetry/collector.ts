import { api, type Session } from "../../services/api";

type EventMetadata = {
  sequence: number;
  time_ms: number;
  type: string;
  stage: string;
  field: string;
  length?: number;
  duration_ms?: number;
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
    const stageFor = (target: EventTarget | null) => {
      if (!(target instanceof HTMLInputElement) || !fields.has(target.id))
        return null;
      return target.id === "username" || target.id === "password"
        ? "login" as const
        : "transfer" as const;
    };
    const pressedKeys = new Map<string, { started: number; stage: "login" | "transfer"; field: string }>();
    const keydown = (event: KeyboardEvent) => {
      const target = event.target;
      const stage = stageFor(target);
      if (!stage || !(target instanceof HTMLInputElement)) return;
      if (event.key === "Backspace" || event.key === "Delete")
        collect("correction", stage, target.id);
      collect("key_press", stage, target.id, event.repeat ? 1 : 0);
      if (!event.repeat)
        pressedKeys.set(event.code, { started: performance.now(), stage, field: target.id });
    };
    const keyup = (event: KeyboardEvent) => {
      const press = pressedKeys.get(event.code);
      if (!press) return;
      pressedKeys.delete(event.code);
      collect("key_dwell", press.stage, press.field, undefined,
        Math.min(5000, Math.max(0, performance.now() - press.started)));
    };
    const focus = (event: FocusEvent) => {
      const target = event.target;
      const stage = stageFor(target);
      if (stage && target instanceof HTMLInputElement)
        collect("focus", stage, target.id);
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
        x: Math.max(0, Math.min(1, event.clientX / Math.max(1, window.innerWidth))),
        y: Math.max(0, Math.min(1, event.clientY / Math.max(1, window.innerHeight))),
      });
    };
    document.addEventListener("keydown", keydown);
    document.addEventListener("keyup", keyup);
    document.addEventListener("focusin", focus);
    document.addEventListener("pointermove", pointer);
    removeListeners = () => {
      document.removeEventListener("keydown", keydown);
      document.removeEventListener("keyup", keyup);
      document.removeEventListener("focusin", focus);
      document.removeEventListener("pointermove", pointer);
      pressedKeys.clear();
    };
  }
}
export function collect(
  type: string,
  stage: "login" | "transfer",
  field: string,
  length?: number,
  durationMs?: number,
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
    ...(durationMs === undefined ? {} : { duration_ms: durationMs }),
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
