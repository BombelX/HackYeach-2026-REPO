import type { RecEvent } from "../types";

function stamp(): Pick<RecEvent, "t_perf" | "t_epoch"> {
  return { t_perf: performance.now(), t_epoch: Date.now() };
}

function fieldOf(el: EventTarget | null): string | null {
  if (!(el instanceof HTMLElement)) return null;
  return el.getAttribute("data-field") || el.id || el.getAttribute("name");
}

function categorize(key: string, code: string): string {
  if (key === "Backspace" || code === "Backspace") return "backspace";
  if (key === "Tab") return "tab";
  if (key === "Enter") return "enter";
  if (key === "Escape") return "escape";
  if (key === " ") return "space";
  if (key.length === 1 && key >= "0" && key <= "9") return "digit";
  if (key.length === 1 && /[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/.test(key)) return "letter";
  if (key.length === 1) return "symbol";
  if (code.startsWith("Arrow")) return "arrow";
  return "special";
}

export function startEventCapture(emit: (e: RecEvent) => void): () => void {
  const onKey = (type: "keydown" | "keyup") => (ev: KeyboardEvent) => {
    emit({
      ...stamp(),
      type,
      payload: {
        code: ev.code,
        key: ev.key,
        category: categorize(ev.key, ev.code),
        repeat: ev.repeat,
        location: ev.location,
        alt: ev.altKey,
        ctrl: ev.ctrlKey,
        shift: ev.shiftKey,
        meta: ev.metaKey,
        field: fieldOf(ev.target),
        timestamp: ev.timeStamp,
      },
    });
  };

  const onInput = (ev: Event) => {
    const e = ev as InputEvent;
    emit({
      ...stamp(),
      type: "input",
      payload: {
        inputType: e.inputType ?? "unknown",
        data: e.data ?? null,
        isComposing: e.isComposing,
        field: fieldOf(e.target),
        valueLength: e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
          ? e.target.value.length
          : null,
      },
    });
  };

  const clipboard = (type: string) => (ev: ClipboardEvent) => {
    emit({
      ...stamp(),
      type,
      payload: {
        field: fieldOf(ev.target),
        types: ev.clipboardData ? Array.from(ev.clipboardData.types) : [],
        textLength: ev.clipboardData?.getData("text")?.length ?? null,
      },
    });
  };

  const onPointer = (type: string) => (ev: PointerEvent) => {
    const coalesced = typeof ev.getCoalescedEvents === "function" ? ev.getCoalescedEvents() : [ev];
    emit({
      ...stamp(),
      type,
      payload: {
        pointerId: ev.pointerId,
        pointerType: ev.pointerType,
        isPrimary: ev.isPrimary,
        button: ev.button,
        buttons: ev.buttons,
        pressure: ev.pressure,
        tangentialPressure: ev.tangentialPressure,
        tiltX: ev.tiltX,
        tiltY: ev.tiltY,
        twist: ev.twist,
        width: ev.width,
        height: ev.height,
        field: fieldOf(ev.target),
        samples: coalesced.map((s) => ({
          t: s.timeStamp,
          x: s.clientX,
          y: s.clientY,
          pressure: s.pressure,
          altitudeAngle: (s as PointerEvent & { altitudeAngle?: number }).altitudeAngle,
          azimuthAngle: (s as PointerEvent & { azimuthAngle?: number }).azimuthAngle,
        })),
      },
    });
  };

  const onWheel = (ev: WheelEvent) => {
    emit({
      ...stamp(),
      type: "wheel",
      payload: {
        deltaX: ev.deltaX,
        deltaY: ev.deltaY,
        deltaZ: ev.deltaZ,
        deltaMode: ev.deltaMode,
        field: fieldOf(ev.target),
      },
    });
  };

  const onScroll = () => {
    emit({
      ...stamp(),
      type: "scroll",
      payload: { x: window.scrollX, y: window.scrollY },
    });
  };

  const onClick = (ev: MouseEvent) => {
    emit({
      ...stamp(),
      type: "click",
      payload: {
        x: ev.clientX,
        y: ev.clientY,
        button: ev.button,
        field: fieldOf(ev.target),
        tag: ev.target instanceof HTMLElement ? ev.target.tagName : null,
      },
    });
  };

  const onFocus = (type: "focus" | "blur") => (ev: FocusEvent) => {
    emit({
      ...stamp(),
      type: type === "focus" ? "field_focus" : "field_blur",
      payload: { field: fieldOf(ev.target) },
    });
  };

  const onVis = () => {
    emit({
      ...stamp(),
      type: "visibility",
      payload: { state: document.visibilityState, hidden: document.hidden },
    });
  };

  const onWin = (type: string) => () => {
    emit({
      ...stamp(),
      type,
      payload: {
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
      },
    });
  };

  const onSel = () => {
    const sel = document.getSelection();
    emit({
      ...stamp(),
      type: "selectionchange",
      payload: { length: sel?.toString().length ?? 0 },
    });
  };

  const keydown = onKey("keydown");
  const keyup = onKey("keyup");
  const pointermove = onPointer("pointermove");
  const pointerdown = onPointer("pointerdown");
  const pointerup = onPointer("pointerup");
  const paste = clipboard("paste");
  const copy = clipboard("copy");
  const cut = clipboard("cut");
  const focusin = onFocus("focus");
  const focusout = onFocus("blur");
  const winFocus = onWin("window_focus");
  const winBlur = onWin("window_blur");
  const resize = onWin("resize");

  window.addEventListener("keydown", keydown, true);
  window.addEventListener("keyup", keyup, true);
  window.addEventListener("input", onInput, true);
  window.addEventListener("paste", paste, true);
  window.addEventListener("copy", copy, true);
  window.addEventListener("cut", cut, true);
  window.addEventListener("pointermove", pointermove, { capture: true, passive: true });
  window.addEventListener("pointerdown", pointerdown, { capture: true, passive: true });
  window.addEventListener("pointerup", pointerup, { capture: true, passive: true });
  window.addEventListener("wheel", onWheel, { capture: true, passive: true });
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("click", onClick, true);
  window.addEventListener("focusin", focusin, true);
  window.addEventListener("focusout", focusout, true);
  window.addEventListener("resize", resize);
  window.addEventListener("focus", winFocus);
  window.addEventListener("blur", winBlur);
  document.addEventListener("visibilitychange", onVis);
  document.addEventListener("selectionchange", onSel);

  return () => {
    window.removeEventListener("keydown", keydown, true);
    window.removeEventListener("keyup", keyup, true);
    window.removeEventListener("input", onInput, true);
    window.removeEventListener("paste", paste, true);
    window.removeEventListener("copy", copy, true);
    window.removeEventListener("cut", cut, true);
    window.removeEventListener("pointermove", pointermove, true);
    window.removeEventListener("pointerdown", pointerdown, true);
    window.removeEventListener("pointerup", pointerup, true);
    window.removeEventListener("wheel", onWheel, true);
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("click", onClick, true);
    window.removeEventListener("focusin", focusin, true);
    window.removeEventListener("focusout", focusout, true);
    window.removeEventListener("resize", resize);
    window.removeEventListener("focus", winFocus);
    window.removeEventListener("blur", winBlur);
    document.removeEventListener("visibilitychange", onVis);
    document.removeEventListener("selectionchange", onSel);
  };
}

export function markStage(emit: (e: RecEvent) => void, stage: string, kind: "start" | "end") {
  emit({
    t_perf: performance.now(),
    t_epoch: Date.now(),
    type: kind === "start" ? "stage_start" : "stage_end",
    payload: { stage },
  });
}
