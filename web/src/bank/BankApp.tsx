import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { playDictation, playScam, stopSpeech, type CallScript } from "../protocol/speech";
import { useProtocol } from "../protocol/ProtocolContext";

type Phase = "id" | "password" | "dash" | "transfer" | "confirm" | "success";

const TIMER_SECONDS: Partial<Record<string, number>> = { intruder: 90, scam: 120 };
const CALL_DELAY_MS = 2500;

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
  const [phoneOn, setPhoneOn] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [deviceAlert, setDeviceAlert] = useState(false);
  const [birthGuess, setBirthGuess] = useState("");
  const [balance, setBalance] = useState(acc?.balance ?? 0);
  const startedAt = useRef(performance.now());
  const loggedInAt = useRef<number | null>(null);
  const callCancel = useRef({ cancelled: false });
  const callStarted = useRef(false);
  const previewRef = useRef<HTMLVideoElement | null>(null);

  const loggedIn = phase !== "id" && phase !== "password";

  const script: CallScript | null = useMemo(() => {
    if (!acc) return null;
    if (condition === "dictation") {
      return { payee: acc.invoice.name, nrb: acc.invoice.nrb, amount: acc.invoice.amount, title: acc.invoice.title };
    }
    if (condition === "scam") {
      return {
        payee: "Rachunek techniczny Bank24",
        nrb: acc.tech_account.nrb,
        amount: Math.floor(acc.balance),
        title: "Zabezpieczenie środków",
      };
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

  const startCall = useCallback(async () => {
    if (!script) return;
    stopSpeech();
    callCancel.current.cancelled = true;
    const c = { cancelled: false };
    callCancel.current = c;
    setPhoneOn(true);
    recorder?.emit({
      t_perf: performance.now(),
      t_epoch: Date.now(),
      type: "call_start",
      payload: { condition },
    });
    const play = condition === "scam" ? playScam : playDictation;
    await play(script, (line) => !c.cancelled && setTranscript(line), c);
    if (!c.cancelled) {
      recorder?.emit({ t_perf: performance.now(), t_epoch: Date.now(), type: "call_end", payload: { condition } });
    }
  }, [script, condition, recorder]);

  useEffect(() => {
    if (!loggedIn || !script || callStarted.current) return;
    callStarted.current = true;
    const t = window.setTimeout(() => void startCall(), CALL_DELAY_MS);
    return () => window.clearTimeout(t);
  }, [loggedIn, script, startCall]);

  useEffect(() => {
    if (!sessionId || !script) return;
    const id = window.setInterval(async () => {
      try {
        const { commands } = await api.commands(sessionId);
        if (commands.some((c) => c.command === "start_call")) void startCall();
      } catch {
        /* server temporarily unreachable */
      }
    }, 2000);
    return () => window.clearInterval(id);
  }, [sessionId, script, startCall]);

  useEffect(
    () => () => {
      callCancel.current.cancelled = true;
      stopSpeech();
    },
    [],
  );

  if (!acc) return null;

  const goStage = (from: string, to: string, next: Phase) => {
    recorder?.stage(from, "end");
    recorder?.stage(to, "start");
    setPhase(next);
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
    callCancel.current.cancelled = true;
    stopSpeech();
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
          <h3>Przelew z telefonu</h3>
          <p className="muted">Dane do przelewu podyktuje Ci księgowa. Słuchaj i wpisuj na bieżąco.</p>
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
                  onClick={() => goStage("transfer", "confirm", "confirm")}
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

      {phase === "confirm" && (
        <div className="dash transfer-form">
          <div className="card">
            <h2>Potwierdź kodem SMS</h2>
            <p>
              {payee} · <span className="nrb">{nrb}</span> · {money(parseAmount(amount))}
            </p>
            {condition === "intruder" ? (
              <p className="tiny">Kod jest na kartce z wycieku.</p>
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

      {phoneOn && (
        <div className="phone">
          <div className="pulse">☎</div>
          <div style={{ textAlign: "center", fontWeight: 700 }}>
            {condition === "scam" ? "Dział bezpieczeństwa Bank24" : "Księgowość"}
          </div>
          <div className="transcript">{transcript}</div>
          <div className="row" style={{ justifyContent: "center", marginTop: 8 }}>
            <button className="btn secondary" onClick={() => void startCall()}>
              Powtórz
            </button>
          </div>
        </div>
      )}

      <video ref={previewRef} className="cam-preview" muted playsInline />
    </div>
  );
}
