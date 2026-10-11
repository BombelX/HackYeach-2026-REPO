import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useProtocol } from "../protocol/ProtocolContext";
import { ChatPanel, type ChatStep } from "./ChatPanel";
import type { SuspiciousRisk } from "../types";

type Phase = "id" | "password" | "dash" | "transfer" | "risk" | "confirm" | "success";

const TIMER_SECONDS: Partial<Record<string, number>> = { intruder: 90, scam: 120 };
const CHAT_DELAY_MS = 2500;

function money(n: number) {
  return n.toLocaleString("en-GB", { style: "currency", currency: "PLN" });
}

function digitsOnly(s: string) {
  return s.replace(/\D/g, "").slice(0, 26);
}

function formatNrbInput(s: string) {
  const d = digitsOnly(s);
  if (d.length <= 2) return d;
  const parts = [d.slice(0, 2)];
  for (let i = 2; i < d.length; i += 4) parts.push(d.slice(i, i + 4));
  return parts.join(" ");
}

function parseAmount(s: string) {
  const n = Number(s.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(n) ? n : 0;
}

export function BankApp() {
  const { actingIdentity, identity, victim, condition, recorder, finishBank, sessionId } = useProtocol();
  const acc = actingIdentity;
  const [phase, setPhase] = useState<Phase>("id");
  const [clientId, setClientId] = useState("");
  const [password, setPassword] = useState("");
  const [loginErr, setLoginErr] = useState<string | null>(null);
  const [payee, setPayee] = useState("");
  const [nrb, setNrb] = useState("");
  const [amount, setAmount] = useState("");
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [confirmErr, setConfirmErr] = useState<string | null>(null);
  const [showLeak, setShowLeak] = useState(condition === "intruder");
  const [peekLeak, setPeekLeak] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const [chatOn, setChatOn] = useState(false);
  const [chatRun, setChatRun] = useState(0);
  const chatReplies = useRef<string[]>([]);
  const [deviceAlert, setDeviceAlert] = useState(false);
  const [birthGuess, setBirthGuess] = useState("");
  const [balance, setBalance] = useState(acc?.balance ?? 0);
  const [risk, setRisk] = useState<SuspiciousRisk | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const startedAt = useRef(performance.now());
  const loggedInAt = useRef<number | null>(null);
  const chatStarted = useRef(false);
  const previewRef = useRef<HTMLVideoElement | null>(null);

  const loggedIn = phase !== "id" && phase !== "password";

  const chatSteps: ChatStep[] | null = useMemo(() => {
    if (!acc) return null;
    if (condition === "dictation") {
      const inv = acc.invoice;
      return [
        { delayMs: 800, text: "Hi, this is Anna from accounting :)" },
        { delayMs: 2500, text: `I have an invoice from ${inv.issuer} that needs paying today. I will send you the details; enter them into a new transfer.` },
        { delayMs: 3000, text: `Recipient: ${inv.name}` },
        { delayMs: 2500, text: `Nr konta: ${inv.nrb_display}` },
        { delayMs: 2500, text: `Amount: ${money(inv.amount)}` },
        { delayMs: 2000, text: `Reference: ${inv.title}` },
        { delayMs: 2000, text: "Let me know when you send the transfer.", awaitReplyMs: 120_000 },
        { delayMs: 1500, text: "Great, thanks!" },
      ];
    }
    if (condition === "scam") {
      const tech = digitsOnly(acc.tech_account.nrb);
      // Swap the tail so the "corrected" account looks almost identical to the first one.
      const tech2 = tech.slice(0, 22) + tech.slice(22).split("").reverse().join("");
      const amount = Math.floor(acc.balance);
      return [
        { delayMs: 500, kind: "alert", text: "⚠ Unusual sign-in detected on your account (Android · Lagos, Nigeria). A security consultant has joined the chat." },
        { delayMs: 2000, text: "Hello, Marek Wisniewski, Bank24 Security Department. We can see an active attempt to move funds out of your account." },
        { delayMs: 2500, text: "Are you at your computer right now? Please reply.", awaitReplyMs: 20_000 },
        { delayMs: 1500, text: "Thank you. Please do NOT sign out; that would interrupt the security procedure." },
        { delayMs: 2500, text: "The funds must be moved to the bank's technical account immediately. This is standard procedure; the money will return within 24 hours." },
        { delayMs: 2500, text: "Recipient: Bank24 technical account" },
        { delayMs: 2000, text: `Number: ${formatNrbInput(tech)}` },
        { delayMs: 2000, text: `Amount: ${money(amount)} – the entire balance, otherwise the criminal will get there first.` },
        { delayMs: 4000, kind: "alert", text: "⚠ Failed transfer authorization attempt from device: Android · Lagos" },
        { delayMs: 3000, text: "Correction! The previous account was just compromised. Please use the NEW number:" },
        { delayMs: 1500, text: `Number: ${formatNrbInput(tech2)}` },
        { delayMs: 2000, text: "Reference: FUNDS PROTECTION 4471" },
        { delayMs: 3000, text: "You will receive an SMS code shortly. Please type it HERE in the chat; I need to verify the transaction on our side.", awaitReplyMs: 40_000 },
        { delayMs: 2000, text: "Please hurry, the system will lock your account shortly." },
        { delayMs: 15_000, text: "Hello? Are you there? Every second counts." },
      ];
    }
    return null;
  }, [acc, condition]);

  useEffect(() => {
    const video = previewRef.current;
    const stream = recorder?.stream;
    if (!video || !stream) return;
    video.srcObject = stream;
    void video.play().catch(() => undefined);
  }, [recorder]);

  useEffect(() => {
    if (condition !== "intruder") return;
    const t = window.setTimeout(() => setShowLeak(false), 20_000);
    return () => window.clearTimeout(t);
  }, [condition]);

  useEffect(() => {
    if (secondsLeft === null) return;
    const id = window.setInterval(() => {
      setSecondsLeft((n) => (n === null || n <= 0 ? 0 : n - 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, [secondsLeft === null]);

  useEffect(() => {
    if (condition !== "intruder" || !loggedIn) return;
    const t = window.setTimeout(() => setDeviceAlert(true), 15_000 + Math.random() * 30_000);
    return () => window.clearTimeout(t);
  }, [condition, loggedIn]);

  const startChat = useCallback(() => {
    if (!chatSteps) return;
    setChatOn(true);
    setChatRun((n) => n + 1);
    recorder?.emit({
      t_perf: performance.now(),
      t_epoch: Date.now(),
      type: "chat_start",
      payload: { condition },
    });
  }, [chatSteps, condition, recorder]);

  const onChatEvent = useCallback(
    (type: string, payload: Record<string, unknown>) => {
      if (type === "chat_reply") {
        const text = String(payload.text ?? "");
        chatReplies.current.push(text);
        payload = { ...payload, contains_sms_code: !!acc && text.includes(acc.sms_code) };
      }
      recorder?.emit({ t_perf: performance.now(), t_epoch: Date.now(), type, payload: { condition, ...payload } });
    },
    [acc, condition, recorder],
  );

  useEffect(() => {
    if (!loggedIn || !chatSteps || chatStarted.current) return;
    chatStarted.current = true;
    const t = window.setTimeout(startChat, CHAT_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [loggedIn, chatSteps, startChat]);

  useEffect(() => {
    if (!sessionId || !chatSteps) return;
    const id = window.setInterval(async () => {
      try {
        const { commands } = await api.commands(sessionId);
        if (commands.some((c) => c.command === "start_call")) startChat();
      } catch {
        /* server temporarily unreachable */
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [sessionId, chatSteps, startChat]);

  const loadRisk = useCallback(async () => {
    if (!sessionId) return;
    setRiskLoading(true);
    try {
      setRisk(await api.suspiciousRisk(sessionId));
    } catch {
      // A mock transfer must always show a score, even if the local API restarts.
      setRisk({ status: "scored", session_id: sessionId, score: 0 });
    } finally {
      setRiskLoading(false);
    }
  }, [sessionId]);

  if (!acc) return null;

  const goStage = (from: string, to: string, next: Phase) => {
    recorder?.stage(from, "end");
    recorder?.stage(to, "start");
    setPhase(next);
  };

  const submitTransferData = () => {
    // Page two must be visible instantly for the showcase. The API updates this
    // number with the model result once the just-recorded data has been flushed.
    setRisk({ status: "scored", session_id: sessionId ?? "", score: 0 });
    goStage("transfer", "risk", "risk");
    void recorder?.flush().then(() => loadRisk());
  };

  const submitId = () => {
    if (clientId.trim().toLowerCase() !== acc.client_id) {
      setLoginErr("We do not recognize this identifier.");
      return;
    }
    setLoginErr(null);
    goStage("login", "password", "password");
  };

  const submitPassword = () => {
    if (password.trim().toLowerCase() !== acc.password) {
      setLoginErr("Incorrect password. Try again.");
      return;
    }
    setLoginErr(null);
    loggedInAt.current = performance.now();
    const limit = condition ? TIMER_SECONDS[condition] : undefined;
    if (limit) setSecondsLeft(limit);
    goStage("password", "dashboard", "dash");
  };

  const confirm = () => {
    if (code.trim() !== acc.sms_code) {
      setConfirmErr("Incorrect code. Check the SMS.");
      return;
    }
    setBalance((b) => b - parseAmount(amount));
    setConfirmErr(null);
    goStage("confirm", "success", "success");
  };

  const wrapUp = () => {
    const now = performance.now();
    void finishBank({
      success: true,
      transferred: parseAmount(amount),
      duration_s: (now - startedAt.current) / 1000,
      login_s: loggedInAt.current ? (loggedInAt.current - startedAt.current) / 1000 : null,
      after_login_s: loggedInAt.current ? (now - loggedInAt.current) / 1000 : null,
      nrb_digits: digitsOnly(nrb),
      payee,
      title,
      timed_out: secondsLeft === 0,
      device_alert_answered: birthGuess.length > 0,
      birth_match: birthGuess === (victim?.identity.birth_date ?? ""),
      chat_replies: chatReplies.current.length,
      sms_code_shared_in_chat: chatReplies.current.some((r) => r.includes(acc.sms_code)),
    });
  };

  const referenceCard = () => {
    if (condition === "intruder") {
      return (
        <div className="card">
          <h3>Your reference card</h3>
          <p className="tiny">The mule account to which you transfer money. Copy the number manually.</p>
          <div className="invoice">
            <div>Recipient: {identity?.full_name}</div>
            <div className="nrb">Account: {identity?.nrb_display}</div>
            <div>Amount: as much as possible</div>
          </div>
        </div>
      );
    }
    if (condition === "dictation") {
      return (
        <div className="card">
          <h3>Transfer for accounting</h3>
          <p className="muted">The accountant will send transfer details in the chat beside this page.</p>
        </div>
      );
    }
    if (condition === "scam") {
      return (
        <div className="card">
          <h3>Recent transactions</h3>
          <div className="tx">
            <span>Biedronka Kraków</span>
            <span>-PLN 84.20</span>
          </div>
          <div className="tx">
            <span>Salary</span>
            <span>+PLN 5,420.00</span>
          </div>
          <div className="tx">
            <span>Netflix</span>
            <span>-PLN 43.00</span>
          </div>
        </div>
      );
    }
    return (
      <div className="card">
        <h3>Invoice to pay</h3>
        <p className="tiny">Copy the details into the transfer form.</p>
        <div className="invoice">
          <div>{acc.invoice.issuer}</div>
          <div>Recipient: {acc.invoice.name}</div>
          <div className="nrb">Account: {acc.invoice.nrb_display}</div>
          <div>Amount: {money(acc.invoice.amount)}</div>
          <div>Reference: {acc.invoice.title}</div>
        </div>
      </div>
    );
  };

  return (
    <div className="bank">
      <header className="bank-top">
        <div className="brand">
          <span className="brand-mark" />
          Bank24
        </div>
        <nav>
          <a>Accounts</a>
          <a>Transfers</a>
          <a>History</a>
        </nav>
        <span className="research-flag">research page</span>
      </header>

      {secondsLeft !== null && loggedIn && phase !== "success" && (
        <div className={`banner ${condition === "scam" ? "" : "warn"}`}>
          <span>
            {condition === "scam" ? "Account will be locked in" : "Owner may return in"} {secondsLeft} s
          </span>
          <span>Balance: {money(balance)}</span>
        </div>
      )}

      {!loggedIn && (
        <div className="login-wrap">
          <div className="login-hero">
            <h2>Welcome to online banking</h2>
            <p>Sign in with your client ID, then your password.</p>
            <p className="tiny">This is not a real bank. Do not enter credentials from your real bank.</p>
          </div>
          <div className="login-panel">
            <div className="login-box">
              <h1>{phase === "id" ? "Sign in to Bank24" : "Password"}</h1>
              <p className="sub">
                {phase === "id" ? "Enter your client ID" : `Welcome, ${acc.first_name}. Enter password.`}
              </p>
              {phase === "id" ? (
                <>
                  <div className="field">
                    <label htmlFor="client_id">ID</label>
                    <input
                      id="client_id"
                      data-field="client_id"
                      autoComplete="off"
                      autoFocus
                      value={clientId}
                      onChange={(e) => setClientId(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submitId()}
                    />
                  </div>
                  {loginErr && <p className="error">{loginErr}</p>}
                  <button className="btn" data-field="submit" onClick={submitId}>
                    Continue
                  </button>
                </>
              ) : (
                <>
                  <div className="field">
                    <label htmlFor="password">Password</label>
                    <input
                      id="password"
                      data-field="password"
                      type="password"
                      autoComplete="off"
                      autoFocus
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && submitPassword()}
                    />
                  </div>
                  {loginErr && <p className="error">{loginErr}</p>}
                  <div className="row">
                    <button className="btn secondary" onClick={() => setPhase("id")}>
                      Back
                    </button>
                    <button className="btn" data-field="submit" onClick={submitPassword}>
                      Sign in
                    </button>
                  </div>
                </>
              )}
              <div className="links">
                <span className="tiny">New to Bank24</span>
                <span className="tiny">Forgot your password?</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {phase === "dash" && (
        <div className="dash">
          <p className="muted">Signed in as {acc.full_name}</p>
          <div className="dash-grid">
            <div className="card">
              <div className="muted">Current account</div>
              <div className="nrb">{acc.nrb_display}</div>
              <div className="balance">{money(balance)}</div>
              <div className="muted">Available funds</div>
              <div className="row" style={{ marginTop: 16 }}>
                <button
                  className="btn accent"
                  data-field="open_transfer"
                  onClick={() => goStage("dashboard", "transfer", "transfer")}
                >
                  New transfer
                </button>
              </div>
            </div>
            {referenceCard()}
          </div>
        </div>
      )}

      {phase === "transfer" && (
        <div className="dash">
          <div className="dash-grid">
            <div className="card">
              <div className="steps">
                <span className="on">1. Details</span>
                <span>2. Confirmation</span>
                <span>3. Finish</span>
              </div>
              <h2>Standard transfer</h2>
              <p className="muted">From account {acc.nrb_display} · available {money(balance)}</p>
              <div className="field">
                <label htmlFor="payee">Recipient name</label>
                <input
                  id="payee"
                  data-field="payee"
                  autoComplete="off"
                  value={payee}
                  onChange={(e) => setPayee(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="nrb">Account number (26 digits)</label>
                <input
                  id="nrb"
                  data-field="nrb"
                  className="nrb"
                  autoComplete="off"
                  value={nrb}
                  onChange={(e) => setNrb(formatNrbInput(e.target.value))}
                  inputMode="numeric"
                />
                <span className="tiny">{digitsOnly(nrb).length} / 26 digits</span>
              </div>
              <div className="field">
                <label htmlFor="amount">Amount (PLN)</label>
                <input
                  id="amount"
                  data-field="amount"
                  autoComplete="off"
                  inputMode="decimal"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="title">Reference</label>
                <input
                  id="title"
                  data-field="title"
                  autoComplete="off"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </div>
              <div className="row">
                <button className="btn secondary" onClick={() => goStage("transfer", "dashboard", "dash")}>
                  Cancel
                </button>
                <button
                  className="btn"
                  data-field="transfer"
                  onClick={submitTransferData}
                  disabled={digitsOnly(nrb).length !== 26 || !payee.trim() || parseAmount(amount) <= 0}
                >
                  Continue
                </button>
              </div>
            </div>
            {referenceCard()}
          </div>
        </div>
      )}

      {phase === "risk" && (
        <div className="dash transfer-form">
          <div className="card risk-card">
            <div className="steps">
              <span>1. Details</span>
              <span className="on">2. Risk assessment</span>
              <span>3. Confirmation</span>
              <span>4. Finish</span>
            </div>
            <h2>Transfer risk assessment</h2>
            <p className="muted">Result based on camera recording and typing telemetry.</p>
            <div className="risk-score">{risk?.score ?? 0}<span>/100</span></div>
            {riskLoading && <p className="tiny">Updating result…</p>}
            <div className="row">
              <button className="btn secondary" onClick={() => goStage("risk", "transfer", "transfer")}>Edit details</button>
              <button className="btn" onClick={() => goStage("risk", "confirm", "confirm")}>Continue</button>
            </div>
          </div>
        </div>
      )}

      {phase === "confirm" && (
        <div className="dash transfer-form">
          <div className="card">
            <h2>Confirm with SMS code</h2>
            <p>
              {payee} · <span className="nrb">{nrb}</span> · {money(parseAmount(amount))}
            </p>
            {condition === "intruder" ? (
              <p className="tiny">The code is on the leaked-credentials card.</p>
            ) : condition === "scam" ? (
              <p className="invoice">
                SMS from Bank24: Code {acc.sms_code} for transfer of {money(parseAmount(amount))}. Never share this code with anyone, including bank staff.
              </p>
            ) : (
              <p className="invoice">SMS from Bank24: Your transfer code is {acc.sms_code}</p>
            )}
            <div className="field">
              <label htmlFor="sms_code">SMS code</label>
              <input
                id="sms_code"
                data-field="sms_code"
                inputMode="numeric"
                autoComplete="off"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && confirm()}
              />
            </div>
            {confirmErr && <p className="error">{confirmErr}</p>}
            <div className="row">
              <button className="btn secondary" onClick={() => goStage("confirm", "transfer", "transfer")}>
                Back
              </button>
              <button className="btn" data-field="confirm" onClick={confirm}>
                Approve transfer
              </button>
            </div>
          </div>
        </div>
      )}

      {phase === "success" && (
        <div className="dash">
          <div className="card">
            <h2 className="ok">Transfer accepted</h2>
            <p>
              {money(parseAmount(amount))} do {payee}
            </p>
            <p className="nrb">{nrb}</p>
            <button className="btn" onClick={wrapUp}>
              Finish session
            </button>
          </div>
        </div>
      )}

      <p className="footer-note">Bank24 (research page) — this is not a real bank.</p>

      {showLeak && victim && (
        <div className="overlay">
          <div className="leak">
            <div className="hdr">Telegram · bank24_leak.txt</div>
            <div>login: {victim.identity.client_id}</div>
            <div>password: {victim.identity.password}</div>
            <div>sms: {victim.identity.sms_code}</div>
            <div>imie: {victim.identity.full_name}</div>
            <p className="tiny">The card will disappear in a few seconds. Remember the details.</p>
            <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setShowLeak(false)}>
              I have memorized it
            </button>
          </div>
        </div>
      )}

      {condition === "intruder" && !showLeak && (phase === "id" || phase === "password" || phase === "confirm") && (
        <button
          className="btn secondary"
          style={{ position: "fixed", left: 12, top: 76, zIndex: 26 }}
          onClick={() => {
            recorder?.emit({ t_perf: performance.now(), t_epoch: Date.now(), type: "leak_peek", payload: { phase } });
            setPeekLeak(true);
            window.setTimeout(() => setPeekLeak(false), 2000);
          }}
        >
          Peek at the card
        </button>
      )}
      {peekLeak && victim && (
        <div className="leak" style={{ position: "fixed", left: 12, top: 120, zIndex: 35 }}>
          <div>login: {victim.identity.client_id}</div>
          <div>password: {victim.identity.password}</div>
          <div>sms: {victim.identity.sms_code}</div>
        </div>
      )}

      {deviceAlert && (
        <div className="overlay">
          <div className="modal">
            <h3>We detected a sign-in from a new device</h3>
            <p>Verify the account owner identity. Enter the date of birth (YYYY-MM-DD).</p>
            <input
              data-field="birth_date"
              autoComplete="off"
              value={birthGuess}
              onChange={(e) => setBirthGuess(e.target.value)}
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={() => setDeviceAlert(false)}>
                Confirm
              </button>
              <button className="btn secondary" onClick={() => setDeviceAlert(false)}>
                Skip
              </button>
            </div>
          </div>
        </div>
      )}

      {chatOn && chatSteps && (
        <ChatPanel
          title={condition === "scam" ? "Bank24 technical support" : "Anna Nowak · Accounting"}
          subtitle={condition === "scam" ? "Live chat · consultant online" : "Teams · available"}
          variant={condition === "scam" ? "support" : "work"}
          steps={chatSteps}
          runId={chatRun}
          onEvent={onChatEvent}
        />
      )}

      <video ref={previewRef} className="cam-preview" muted playsInline />
    </div>
  );
}
