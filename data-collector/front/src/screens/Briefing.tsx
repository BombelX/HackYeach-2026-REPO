import { useProtocol } from "../protocol/ProtocolContext";
import type { Condition } from "../types";

const COPY: Record<Condition, { title: string; body: string }> = {
  calm_1: {
    title: "Calm session 1",
    body: "Sign in to your account and pay the invoice on the dashboard. Copy all transfer details manually from the invoice. Take your time.",
  },
  calm_2: {
    title: "Calm session 2",
    body: "A second calm session: use your own account and copy the invoice details manually again. We want to observe your usual rhythm.",
  },
  dictation: {
    title: "Chat with the accountant",
    body: "Sign in to your account. A chat will open beside it, and the accountant will send invoice payment details. Copy them into the transfer and reply when you finish.",
  },
  scam: {
    title: "Technical support",
    body: "Sign in as usual. Bank technical support may contact you in the chat. Treat the situation as real and act as you normally would.",
  },
  intruder: {
    title: "Account takeover",
    body: "You will see leaked credentials for 20 seconds. Use them to sign in to someone else's account. After sign-in, you have 90 seconds to transfer as much as possible to the account on your card before the owner notices. A leaderboard is displayed in the hall.",
  },
  calm_3: {
    title: "Final calm session",
    body: "One final calm session on your account. Pay the invoice again, without pressure.",
  },
};

export function Briefing() {
  const { condition, index, join, beginCondition, error } = useProtocol();
  if (!condition || !join) return null;
  const copy = COPY[condition];
  return (
    <div className="study-shell">
      <div className="study-card">
        <p className="tiny">
          Session {index + 1} / {join.condition_order.length}
        </p>
        <h1>{copy.title}</h1>
        <p className="lead">{copy.body}</p>
        {error && <p className="error">{error}</p>}
        <button className="btn accent" onClick={() => void beginCondition()}>
          Open Bank24
        </button>
      </div>
    </div>
  );
}
