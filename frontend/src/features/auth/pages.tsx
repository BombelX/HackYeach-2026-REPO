import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useTask } from "../../app/hooks";
import {
  ErrorNotice,
  Field,
  PageTitle,
  Steps,
  useErrorFocus,
} from "../../design/components";
import {
  api,
  type Challenge,
  refreshSession,
  setCsrf,
  sessionOptions,
  updatePermissions,
} from "../../services/api";
import { collect, flushTelemetry } from "../telemetry/collector";
import { configureTelemetry } from "../telemetry/collector";

const draft = { username: "", password: "", remember: false };
export function clearAuthDraft() {
  draft.username = "";
  draft.password = "";
  draft.remember = false;
}
export function LoginPage() {
  const [values, setValues] = useState({ ...draft });
  const [telemetryOptIn, setTelemetryOptIn] = useState(false);
  const task = useTask();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const session = useQuery(sessionOptions).data;
  useErrorFocus(task.error);
  function change(field: "username" | "password", value: string) {
    draft[field] = value;
    setValues({ ...draft });
    collect("input", "login", field, value.length);
  }
  return (
    <>
      <PageTitle
        title="Zaloguj się do Bank24"
        intro="Uzyskaj dostęp do rachunku i przelewów."
      />
      <form
        aria-busy={task.busy}
        onSubmit={(e) => {
          e.preventDefault();
          void task.run(async () => {
            const permissions = await updatePermissions({
              telemetry: telemetryOptIn,
            });
            configureTelemetry(permissions);
            await flushTelemetry();
            await api<Challenge>("/bank/login", "POST", values);
            draft.password = "";
            const returnTo = searchParams.get("return");
            const suffix =
              returnTo &&
              returnTo.startsWith("/app/") &&
              !returnTo.startsWith("//")
                ? "?return=" + encodeURIComponent(returnTo)
                : "";
            navigate("/verify-login" + suffix);
          });
        }}
      >
        <Field
          id="username"
          label="Login"
          autoComplete="username"
          value={values.username}
          onChange={(e) => change("username", e.target.value)}
          maxLength={100}
          placeholder="Wpisz login"
          required
        />
        <Field
          id="password"
          label="Hasło"
          type="password"
          autoComplete="current-password"
          value={values.password}
          onChange={(e) => change("password", e.target.value)}
          maxLength={256}
          placeholder="Wpisz hasło"
          required
        />
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={values.remember}
            onChange={(e) => {
              draft.remember = e.target.checked;
              setValues({ ...draft });
            }}
          />
          Zapamiętaj to urządzenie
        </label>
        <p className="field-hint device-hint">
          Zapisz urządzenie jako zaufane na 30 dni. Kody logowania i przelewów
          pozostają wymagane. Używaj tylko na własnym urządzeniu.
        </p>
        <label className="optional-permission">
          <input
            type="checkbox"
            checked={telemetryOptIn}
            onChange={(event) => setTelemetryOptIn(event.target.checked)}
          />
          <span>
            <strong>Pomóż ulepszać demonstrację</strong>
            <small>
              Opcjonalne metadane użycia. Nie zbieramy wpisywanych treści. Wybór
              możesz zmienić później.
            </small>
          </span>
        </label>
        <ErrorNotice error={task.error} />
        <button className="primary-button" disabled={task.busy}>
          {task.busy ? "Sprawdzamy dane…" : "Zaloguj się"}
        </button>
      </form>
      {session?.demo_mode && (
        <aside
          className="demo-credentials"
          aria-label="Dane konta demonstracyjnego"
        >
          <strong>Dane do konta demonstracyjnego</strong>
          <p>Wpisz dane ręcznie i poznaj możliwości serwisu.</p>
          <dl>
            <div>
              <dt>Login</dt>
              <dd>anna.demo</dd>
            </div>
            <div>
              <dt>Hasło</dt>
              <dd>bank24</dd>
            </div>
            <div>
              <dt>Kod logowania</dt>
              <dd>1234</dd>
            </div>
          </dl>
        </aside>
      )}
      <Link className="text-button" to="/help?return=%2Flogin">
        Potrzebuję pomocy z logowaniem
      </Link>
    </>
  );
}
export function useCountdown(challenge?: Challenge) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return {
    expires: challenge
      ? Math.max(0, Math.ceil(challenge.expires_at - now / 1000))
      : 0,
    cooldown: challenge
      ? Math.max(0, Math.ceil(challenge.resend_at - now / 1000))
      : 0,
  };
}
export function VerifyLoginPage() {
  const [searchParams] = useSearchParams();
  const query = useQuery({
    queryKey: ["login-challenge"],
    queryFn: () => api<Challenge>("/bank/login-challenge"),
    staleTime: 0,
  });
  const [code, setCode] = useState("");
  const task = useTask();
  const navigate = useNavigate();
  const countdown = useCountdown(query.data);
  useErrorFocus(task.error);
  return (
    <>
      <Steps
        current={1}
        labels={["Dane logowania", "Weryfikacja kodem", "Dostęp do konta"]}
        ariaLabel="Etapy logowania"
      />
      <PageTitle
        title="Wpisz kod logowania"
        intro={`Wpisz ${query.data?.code_length ?? 4}-cyfrowy kod logowania. Nie przekazuj go innym osobom.`}
      />
      {query.data?.demo_mode && (
        <p className="notice">
          Tryb demonstracyjny: kod <strong>1234</strong>. Wiadomość SMS nie jest
          wysyłana.
        </p>
      )}
      <ErrorNotice error={query.error} />
      <form
        aria-busy={task.busy}
        onSubmit={(e) => {
          e.preventDefault();
          void task.run(async () => {
            const result = await api<{ csrf: string }>("/bank/verify", "POST", {
              challenge_id: query.data?.challenge_id,
              code,
            });
            setCsrf(result.csrf);
            clearAuthDraft();
            await refreshSession();
            const returnTo = searchParams.get("return");
            const target =
              returnTo &&
              returnTo.startsWith("/app/") &&
              !returnTo.startsWith("//")
                ? returnTo
                : "/app";
            navigate(target, { replace: true });
          });
        }}
      >
        <Field
          label="Kod potwierdzenia"
          id="code"
          autoComplete="one-time-code"
          inputMode="numeric"
          value={code}
          onChange={(e) =>
            setCode(
              e.target.value
                .replace(/\D/g, "")
                .slice(0, query.data?.code_length ?? 6),
            )
          }
          error={task.fields.code}
          maxLength={query.data?.code_length ?? 6}
          className="otp-code"
          required
          hint={
            query.data
              ? countdown.expires
                ? `Kod ważny jeszcze przez ${countdown.expires} s.`
                : "Kod wygasł. Zamów nowy."
              : "Pobieramy dane kodu…"
          }
        />
        <ErrorNotice error={task.error} />
        <button
          className="primary-button"
          disabled={task.busy || !query.data || !countdown.expires}
        >
          {task.busy ? "Potwierdzamy…" : "Potwierdź logowanie"}
        </button>
      </form>
      <button
        className="text-button"
        disabled={task.busy || countdown.cooldown > 0 || !query.data}
        onClick={() =>
          void task.run(async () => {
            await api("/bank/login-challenge", "POST", {});
            setCode("");
            await query.refetch();
          })
        }
      >
        {countdown.cooldown
          ? `Nowy kod za ${countdown.cooldown} s`
          : "Zamów nowy kod"}
      </button>
      <Link className="text-button" to="/login">
        Wróć do logowania
      </Link>
    </>
  );
}
