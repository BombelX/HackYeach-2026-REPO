import { api, type Session } from "../../services/api";
import { appPathname } from "../../app/path";

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
  width?: number;
  height?: number;
  delta_y?: number;
  env?: Record<string, unknown>;
  keys?: number[];
  features?: number[][];
  status?: number;
};
const page = crypto.randomUUID();
let sequence = 0;
let queue: EventMetadata[] = [];
let enabled = false;
let sessionId: string | undefined;
let busy = false;
let timer: ReturnType<typeof setInterval> | undefined;
let removeListeners: (() => void) | undefined;
export function configureTelemetry(session?: Session) {
  if (sessionId !== session?.session_id) {
    enabled = false; queue = [];
    if (timer) clearInterval(timer);
    timer = undefined; removeListeners?.(); removeListeners = undefined;
    sessionId = session?.session_id;
  }
  enabled = !!session?.telemetry;
  if (!enabled) {
    queue = [];
    if (timer) clearInterval(timer);
    timer = undefined;
    removeListeners?.();
    removeListeners = undefined;
  } else if (!timer) {
    timer = setInterval(() => void flushTelemetry(), 750);
    const push = (type: string, extra: Partial<EventMetadata> = {}) => {
      if (!enabled) return;
      queue.push({ sequence: sequence++, time_ms: performance.now(), type, stage: "transfer", field: "none", ...extra });
    };
    push("environment", { env: {
      platform: navigator.platform, userAgent: navigator.userAgent,
      screen: { width: screen.width, height: screen.height },
      devicePixelRatio, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      language: navigator.language, hardwareConcurrency: navigator.hardwareConcurrency,
      maxTouchPoints: navigator.maxTouchPoints,
    } });
    let pingBusy = false;
    const ping = async () => {
      if (pingBusy || !enabled) return;
      pingBusy = true;
      const started = performance.now();
      try {
        const response = await fetch(import.meta.env.BASE_URL + "health", { signal: AbortSignal.timeout(5000) });
        await response.text();
        if (enabled) push("ping", { duration_ms: performance.now() - started });
      } catch { /* Unavailable measurements stay absent. */ }
      finally { pingBusy = false; }
    };
    void ping();
    const pingTimer = setInterval(() => void ping(), 5000);
    const requestTiming = (event: Event) => push("server_request", (event as CustomEvent).detail);
    window.addEventListener("bank24:request-timing", requestTiming);
    let strokes: { key: number; features: number[]; started: number; ended: number; field: string }[] = [];
    const emitStrokes = () => {
      if (strokes.length >= 16) {
        strokes.sort((a, b) => a.started - b.started);
        strokes.forEach((stroke, index) => {
          const previous = strokes[index - 1];
          const log = (v: number) => Math.sign(v) * Math.log1p(Math.min(3000, Math.abs(v)));
          stroke.features[1] = previous ? log(stroke.started - previous.started) : 0;
          stroke.features[2] = previous ? log(stroke.started - previous.ended) : 0;
        });
        push("keyboard_window", { field: strokes[0].field, keys: strokes.map(s => s.key),
          features: strokes.map(s => s.features), length: strokes.length,
          duration_ms: performance.now() - strokes[0].started });
        strokes = [];
      }
    };
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
    const pressedKeys = new Map<string, { started: number; stage: "login" | "transfer"; field: string; key: number; letter: string }>();
    const keydown = (event: KeyboardEvent) => {
      const target = event.target;
      const stage = stageFor(target);
      if (!stage || !(target instanceof HTMLInputElement) || target.type === "password") return;
      if (event.key === "Backspace" || event.key === "Delete")
        collect("correction", stage, target.id);
      collect("key_press", stage, target.id, event.repeat ? 1 : 0);
      if (!event.repeat)
        pressedKeys.set(event.code, { started: performance.now(), stage, field: target.id,
          key: event.key === "Backspace" ? 9 : Math.min(32767, (event.keyCode || 0) + 1),
          letter: event.key === "Backspace" ? "BKSP" : event.key === "Shift" ? "SHIFT" : event.key });
    };
    const keyup = (event: KeyboardEvent) => {
      const press = pressedKeys.get(event.code);
      if (!press) return;
      pressedKeys.delete(event.code);
      if (strokes.length && (strokes[0].field !== press.field || performance.now() - strokes[strokes.length - 1].ended > 10000)) {
        emitStrokes(); strokes = [];
      }
      const previous = strokes[strokes.length - 1];
      const log = (v: number) => Math.sign(v) * Math.log1p(Math.min(3000, Math.abs(v)));
      const letter = press.letter;
      strokes.push({ key: press.key, started: press.started, ended: performance.now(), field: press.field,
        features: [log(performance.now() - press.started), previous ? log(press.started - previous.started) : 0,
          previous ? log(press.started - previous.ended) : 0, /^[a-zA-Z]$/.test(letter) ? 1 : 0,
          /^[0-9]$/.test(letter) ? 1 : 0, letter === "SHIFT" ? 1 : 0, 0,
          !/^[a-zA-Z0-9]$/.test(letter) && letter !== "SHIFT" ? 1 : 0] });
      if (strokes.length >= 96) emitStrokes();
      collect("key_dwell", press.stage, press.field, undefined,
        Math.min(5000, Math.max(0, performance.now() - press.started)));
    };
    const focus = (event: FocusEvent) => {
      const target = event.target;
      const stage = stageFor(target);
      if (stage && target instanceof HTMLInputElement)
        collect("focus", stage, target.id);
    };
    const keyboardTimer = setInterval(emitStrokes, 3000);
    let lastPointer = 0;
    const pointer = (event: PointerEvent) => {
      const now = performance.now();
      if (event.type === "pointermove" && now - lastPointer < 30) return;
      const stage = appPathname(location.pathname) === "/login" ? "login" : "transfer";
      lastPointer = now;
      if (queue.length >= 100) queue.shift();
      queue.push({
        sequence: sequence++,
        time_ms: now,
        type: event.type === "pointermove" ? "pointer" : event.type,
        stage,
        field: "none",
        width: window.innerWidth, height: window.innerHeight,
        x: Math.max(0, Math.min(1, event.clientX / Math.max(1, window.innerWidth))),
        y: Math.max(0, Math.min(1, event.clientY / Math.max(1, window.innerHeight))),
      });
    };
    const clipboard = (event: Event) => push(event.type);
    const blur = () => { pressedKeys.clear(); push("window_blur"); };
    const visibility = () => { if (document.hidden) push("hidden"); };
    const wheel = (event: WheelEvent) => push("wheel", { delta_y: event.deltaY });
    ["paste", "copy", "cut"].forEach(type => document.addEventListener(type, clipboard));
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", visibility);
    document.addEventListener("wheel", wheel, { passive: true });
    document.addEventListener("pointerdown", pointer);
    document.addEventListener("pointerup", pointer);
    document.addEventListener("click", pointer as unknown as EventListener);
    document.addEventListener("keydown", keydown);
    document.addEventListener("keyup", keyup);
    document.addEventListener("focusin", focus);
    document.addEventListener("pointermove", pointer);
    removeListeners = () => {
      clearInterval(pingTimer); clearInterval(keyboardTimer); strokes = [];
      window.removeEventListener("bank24:request-timing", requestTiming);
      ["paste", "copy", "cut"].forEach(type => document.removeEventListener(type, clipboard));
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", visibility);
      document.removeEventListener("wheel", wheel);
      document.removeEventListener("pointerdown", pointer);
      document.removeEventListener("pointerup", pointer);
      document.removeEventListener("click", pointer as unknown as EventListener);
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
