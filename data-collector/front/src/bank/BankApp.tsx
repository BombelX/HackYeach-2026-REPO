import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useProtocol } from "../protocol/ProtocolContext";
import { ChatPanel, type ChatStep } from "./ChatPanel";
import type { SuspiciousRisk } from "../types";

type Phase = "id" | "password" | "dash" | "transfer" | "risk" | "confirm" | "success";

const TIMER_SECONDS: Partial<Record<string, number>> = { intruder: 90, scam: 120 };
const CHAT_DELAY_MS = 2500;

function money(n: number) {
  return n.toLocaleString("pl-PL", { style: "currency", currency: "PLN" });
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
        { delayMs: 800, text: "Cześć, tu Ania z księgowości :)" },
        { delayMs: 2500, text: `Mam fakturę od ${inv.issuer}, trzeba ją dziś opłacić. Podeślę Ci dane, wpisz je w nowy przelew.` },
        { delayMs: 3000, text: `Odbiorca: ${inv.name}` },
        { delayMs: 2500, text: `Nr konta: ${inv.nrb_display}` },
        { delayMs: 2500, text: `Kwota: ${money(inv.amount)}` },
        { delayMs: 2000, text: `Tytuł: ${inv.title}` },
        { delayMs: 2000, text: "Daj znać, jak puścisz przelew.", awaitReplyMs: 120_000 },
        { delayMs: 1500, text: "Super, dzięki!" },
      ];
    }
    if (condition === "scam") {
      const tech = digitsOnly(acc.tech_account.nrb);
      // Swap the tail so the "corrected" account looks almost identical to the first one.
      const tech2 = tech.slice(0, 22) + tech.slice(22).split("").reverse().join("");
      const amount = Math.floor(acc.balance);
      return [
        { delayMs: 500, kind: "alert", text: "⚠ Wykryto nietypowe logowanie do Twojego konta (Android · Lagos, Nigeria). Konsultant bezpieczeństwa dołączył do czatu." },
        { delayMs: 2000, text: "Dzień dobry, Marek Wiśniewski, Dział Bezpieczeństwa Bank24. Widzimy aktywną próbę wyprowadzenia środków z Pana/Pani konta." },
        { delayMs: 2500, text: "Czy jest Pan/Pani teraz przy komputerze? Proszę odpisać.", awaitReplyMs: 20_000 },
        { delayMs: 1500, text: "Dziękuję. Proszę się NIE wylogowywać, to przerwie procedurę zabezpieczenia." },
        { delayMs: 2500, text: "Środki trzeba natychmiast przenieść na rachunek techniczny banku. To standardowa procedura, pieniądze wrócą na konto w ciągu 24 h." },
        { delayMs: 2500, text: "Odbiorca: Rachunek techniczny Bank24" },
        { delayMs: 2000, text: `Numer: ${formatNrbInput(tech)}` },
        { delayMs: 2000, text: `Kwota: ${money(amount)} – całe saldo, inaczej przestępca zdąży przed nami.` },
        { delayMs: 4000, kind: "alert", text: "⚠ Nieudana próba autoryzacji przelewu z urządzenia: Android · Lagos" },
        { delayMs: 3000, text: "Uwaga, poprawka! Poprzedni rachunek został właśnie przejęty. Proszę użyć NOWEGO numeru:" },
        { delayMs: 1500, text: `Numer: ${formatNrbInput(tech2)}` },
        { delayMs: 2000, text: "Tytuł: ZABEZPIECZENIE SRODKOW 4471" },
        { delayMs: 3000, text: "Za chwilę dostanie Pan/Pani SMS z kodem. Proszę przepisać kod TUTAJ na czacie, muszę zweryfikować operację po naszej stronie.", awaitReplyMs: 40_000 },
        { delayMs: 2000, text: "Proszę się pospieszyć, system zablokuje konto za kilka chwil." },
        { delayMs: 15_000, text: "Halo? Jest Pan/Pani? Każda sekunda się liczy." },
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
      setLoginErr("Nie rozpoznajemy tego identyfikatora.");
      return;
    }
    setLoginErr(null);
    goStage("login", "password", "password");
  };

  const submitPassword = () => {
    if (password.trim().toLowerCase() !== acc.password) {
      setLoginErr("Hasło nieprawidłowe. Spróbuj ponownie.");
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
      setConfirmErr("Nieprawidłowy kod. Sprawdź SMS.");
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
          <h3>Twoja kartka</h3>
          <p className="tiny">Konto „słupa”, na które wyprowadzasz pieniądze. Przepisz numer ręcznie.</p>
          <div className="invoice">
            <div>Odbiorca: {identity?.full_name}</div>
            <div className="nrb">Konto: {identity?.nrb_display}</div>
            <div>Kwota: ile się da</div>
          </div>
        </div>
      );
    }
    if (condition === "dictation") {
      return (
        <div className="card">
          <h3>Przelew dla księgowości</h3>
          <p className="muted">Dane do przelewu przyśle Ci księgowa na czacie obok.</p>
        </div>
      );
    }
    if (condition === "scam") {
      return (
        <div className="card">
          <h3>Ostatnie operacje</h3>
          <div className="tx">
            <span>Biedronka Kraków</span>
            <span>-84,20 zł</span>
          </div>
          <div className="tx">
            <span>Wynagrodzenie</span>
            <span>+5 420,00 zł</span>
          </div>
          <div className="tx">
            <span>Netflix</span>
            <span>-43,00 zł</span>
          </div>
        </div>
      );
    }
    return (
      <div className="card">
        <h3>Faktura do opłacenia</h3>
        <p className="tiny">Przepisz dane do formularza przelewu.</p>
        <div className="invoice">
          <div>{acc.invoice.issuer}</div>
          <div>Odbiorca: {acc.invoice.name}</div>
          <div className="nrb">Konto: {acc.invoice.nrb_display}</div>
          <div>Kwota: {money(acc.invoice.amount)}</div>
          <div>Tytuł: {acc.invoice.title}</div>
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
          <a>Konta</a>
          <a>Przelewy</a>
          <a>Historia</a>
        </nav>
        <span className="research-flag">strona badawcza</span>
      </header>

      {secondsLeft !== null && loggedIn && phase !== "success" && (
        <div className={`banner ${condition === "scam" ? "" : "warn"}`}>
          <span>
            {condition === "scam" ? "Konto zostanie zablokowane za" : "Właściciel może wrócić za"} {secondsLeft} s
          </span>
          <span>Saldo: {money(balance)}</span>
        </div>
      )}

      {!loggedIn && (
        <div className="login-wrap">
          <div className="login-hero">
            <h2>Witamy w bankowości internetowej</h2>
            <p>Zaloguj się identyfikatorem, a następnie hasłem.</p>
            <p className="tiny">To nie jest prawdziwy bank. Nie wpisuj danych z Pekao, mBanku ani ING.</p>
          </div>
          <div className="login-panel">
            <div className="login-box">
              <h1>{phase === "id" ? "Zaloguj się do Bank24" : "Hasło"}</h1>
              <p className="sub">
                {phase === "id" ? "Podaj identyfikator klienta" : `Witaj, ${acc.first_name}. Wpisz hasło.`}
              </p>
              {phase === "id" ? (
                <>
                  <div className="field">
                    <label htmlFor="client_id">Identyfikator</label>
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
                    Dalej
                  </button>
                </>
              ) : (
                <>
                  <div className="field">
                    <label htmlFor="password">Hasło</label>
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
                      Wstecz
                    </button>
                    <button className="btn" data-field="submit" onClick={submitPassword}>
                      Zaloguj
                    </button>
                  </div>
                </>
              )}
              <div className="links">
                <span className="tiny">Pierwszy raz w Bank24</span>
                <span className="tiny">Nie pamiętasz hasła?</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {phase === "dash" && (
        <div className="dash">
          <p className="muted">Zalogowano jako {acc.full_name}</p>
          <div className="dash-grid">
            <div className="card">
              <div className="muted">Rachunek bieżący</div>
              <div className="nrb">{acc.nrb_display}</div>
              <div className="balance">{money(balance)}</div>
              <div className="muted">Dostępne środki</div>
              <div className="row" style={{ marginTop: 16 }}>
                <button
                  className="btn accent"
                  data-field="open_transfer"
                  onClick={() => goStage("dashboard", "transfer", "transfer")}
                >
                  Nowy przelew
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
                <span className="on">1. Dane</span>
                <span>2. Potwierdzenie</span>
                <span>3. Koniec</span>
              </div>
              <h2>Przelew zwykły</h2>
              <p className="muted">Z rachunku {acc.nrb_display} · dostępne {money(balance)}</p>
              <div className="field">
                <label htmlFor="payee">Nazwa odbiorcy</label>
                <input
                  id="payee"
                  data-field="payee"
                  autoComplete="off"
                  value={payee}
                  onChange={(e) => setPayee(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="nrb">Numer rachunku (26 cyfr)</label>
                <input
                  id="nrb"
                  data-field="nrb"
                  className="nrb"
                  autoComplete="off"
                  value={nrb}
                  onChange={(e) => setNrb(formatNrbInput(e.target.value))}
                  inputMode="numeric"
                />
                <span className="tiny">{digitsOnly(nrb).length} / 26 cyfr</span>
              </div>
              <div className="field">
                <label htmlFor="amount">Kwota (PLN)</label>
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
                <label htmlFor="title">Tytuł</label>
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
                  Anuluj
                </button>
                <button
                  className="btn"
                  data-field="transfer"
                  onClick={submitTransferData}
                  disabled={digitsOnly(nrb).length !== 26 || !payee.trim() || parseAmount(amount) <= 0}
                >
                  Dalej
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
              <span>1. Dane</span>
              <span className="on">2. Ocena ryzyka</span>
              <span>3. Potwierdzenie</span>
              <span>4. Koniec</span>
            </div>
            <h2>Ocena ryzyka przelewu</h2>
            <p className="muted">Wynik na podstawie nagrania z kamery i telemetrii wpisywania danych.</p>
            <div className="risk-score">{risk?.score ?? 0}<span>/100</span></div>
            {riskLoading && <p className="tiny">Aktualizacja wyniku…</p>}
            <div className="row">
              <button className="btn secondary" onClick={() => goStage("risk", "transfer", "transfer")}>Edytuj dane</button>
              <button className="btn" onClick={() => goStage("risk", "confirm", "confirm")}>Dalej</button>
            </div>
          </div>
        </div>
      )}

      {phase === "confirm" && (
        <div className="dash transfer-form">
          <div className="card">
            <h2>Potwierdź kodem SMS</h2>
            <p>
              {payee} · <span className="nrb">{nrb}</span> · {money(parseAmount(amount))}
            </p>
            {condition === "intruder" ? (
              <p className="tiny">Kod jest na kartce z wycieku.</p>
            ) : condition === "scam" ? (
              <p className="invoice">
                SMS od Bank24: Kod {acc.sms_code} do przelewu {money(parseAmount(amount))}. Nigdy nie podawaj tego kodu
                nikomu, także pracownikom banku.
              </p>
            ) : (
              <p className="invoice">SMS od Bank24: Twój kod do przelewu to {acc.sms_code}</p>
            )}
            <div className="field">
              <label htmlFor="sms_code">Kod z SMS</label>
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
                Wstecz
              </button>
              <button className="btn" data-field="confirm" onClick={confirm}>
                Zatwierdź przelew
              </button>
            </div>
          </div>
        </div>
      )}

      {phase === "success" && (
        <div className="dash">
          <div className="card">
            <h2 className="ok">Przelew przyjęty</h2>
            <p>
              {money(parseAmount(amount))} do {payee}
            </p>
            <p className="nrb">{nrb}</p>
            <button className="btn" onClick={wrapUp}>
              Zakończ sesję
            </button>
          </div>
        </div>
      )}

      <p className="footer-note">Bank24 (strona badawcza) — to nie jest prawdziwy bank.</p>

      {showLeak && victim && (
        <div className="overlay">
          <div className="leak">
            <div className="hdr">Telegram · wyciek_bank24.txt</div>
            <div>login: {victim.identity.client_id}</div>
            <div>haslo: {victim.identity.password}</div>
            <div>sms: {victim.identity.sms_code}</div>
            <div>imie: {victim.identity.full_name}</div>
            <p className="tiny">Kartka zniknie za kilka sekund. Zapamiętaj dane.</p>
            <button className="btn secondary" style={{ marginTop: 8 }} onClick={() => setShowLeak(false)}>
              Zapamiętałem
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
          Zerknij na kartkę
        </button>
      )}
      {peekLeak && victim && (
        <div className="leak" style={{ position: "fixed", left: 12, top: 120, zIndex: 35 }}>
          <div>login: {victim.identity.client_id}</div>
          <div>haslo: {victim.identity.password}</div>
          <div>sms: {victim.identity.sms_code}</div>
        </div>
      )}

      {deviceAlert && (
        <div className="overlay">
          <div className="modal">
            <h3>Wykryliśmy logowanie z nowego urządzenia</h3>
            <p>Potwierdź tożsamość właściciela konta. Podaj datę urodzenia (RRRR-MM-DD).</p>
            <input
              data-field="birth_date"
              autoComplete="off"
              value={birthGuess}
              onChange={(e) => setBirthGuess(e.target.value)}
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={() => setDeviceAlert(false)}>
                Potwierdź
              </button>
              <button className="btn secondary" onClick={() => setDeviceAlert(false)}>
                Pomiń
              </button>
            </div>
          </div>
        </div>
      )}

      {chatOn && chatSteps && (
        <ChatPanel
          title={condition === "scam" ? "Pomoc techniczna Bank24" : "Anna Nowak · Księgowość"}
          subtitle={condition === "scam" ? "Czat na żywo · konsultant online" : "Teams · dostępna"}
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
