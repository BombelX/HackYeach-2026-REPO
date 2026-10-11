import { useEffect, useRef, useState } from "react";

export type ChatStep = {
  text: string;
  /** Pause before this message appears (typing indicator is shown meanwhile). */
  delayMs: number;
  /** "alert" renders as a red system notice instead of a chat bubble. */
  kind?: "msg" | "alert";
  /** Wait up to this many ms for the participant to reply before continuing. */
  awaitReplyMs?: number;
};

type Line = { from: "them" | "me" | "alert"; text: string };

export function ChatPanel(props: {
  title: string;
  subtitle: string;
  variant: "work" | "support";
  steps: ChatStep[];
  runId: number;
  onEvent: (type: string, payload: Record<string, unknown>) => void;
}) {
  const { title, subtitle, variant, steps, runId, onEvent } = props;
  const [lines, setLines] = useState<Line[]>([]);
  const [typing, setTyping] = useState(false);
  const [draft, setDraft] = useState("");
  const replyWaiter = useRef<(() => void) | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    let cancelled = false;
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    setLines([]);
    void (async () => {
      for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        setTyping(step.kind !== "alert");
        await sleep(step.delayMs);
        if (cancelled) return;
        setTyping(false);
        setLines((l) => [...l, { from: step.kind === "alert" ? "alert" : "them", text: step.text }]);
        onEventRef.current("chat_message", { index: i, kind: step.kind ?? "msg", text: step.text });
        if (step.awaitReplyMs) {
          await Promise.race([
            new Promise<void>((r) => (replyWaiter.current = r)),
            sleep(step.awaitReplyMs),
          ]);
          replyWaiter.current = null;
          if (cancelled) return;
        }
      }
    })();
    return () => {
      cancelled = true;
      replyWaiter.current = null;
    };
  }, [steps, runId]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [lines, typing]);

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setLines((l) => [...l, { from: "me", text }]);
    setDraft("");
    onEventRef.current("chat_reply", { text });
    replyWaiter.current?.();
  };

  return (
    <div className={`chat chat-${variant}`}>
      <div className="chat-head">
        <span className="chat-dot" />
        <div>
          <div className="chat-title">{title}</div>
          <div className="chat-sub">{subtitle}</div>
        </div>
      </div>
      <div className="chat-body" ref={bodyRef}>
        {lines.map((l, i) => (
          <div key={i} className={`chat-line ${l.from}`}>
            {l.text}
          </div>
        ))}
        {typing && <div className="chat-line them typing">pisze…</div>}
      </div>
      <div className="chat-input">
        <input
          data-field="chat_reply"
          autoComplete="off"
          placeholder="Napisz wiadomość…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn" onClick={send}>
          Wyślij
        </button>
      </div>
    </div>
  );
}
