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
        title="Sign in to Bank24"
        intro="Access your account and transfers."
      />
      {searchParams.get("reason") === "anomaly" && (
        <div className="notice error" role="alert">
          <p>
            <strong>Signed out for security reasons.</strong>
          </p>
          <p>
            Camera analysis found a significant mismatch with the account owner profile. If this is your account, sign in again.
          </p>
        </div>
      )}
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
          placeholder="Enter username"
          required
        />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={values.password}
          onChange={(e) => change("password", e.target.value)}
          maxLength={256}
          placeholder="Enter password"
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
          Remember this device
        </label>
        <p className="field-hint device-hint">
          Trust this device for 30 days. Sign-in and transfer codes are still required. Use this only on your own device.
        </p>
        <label className="optional-permission">
          <input
            type="checkbox"
            checked={telemetryOptIn}
            onChange={(event) => setTelemetryOptIn(event.target.checked)}
          />
          <span>
            <strong>Help improve the demo</strong>
            <small>
              Optional analysis of typing rhythm, mouse movements, browser/device details and connection timings. Non-password key identifiers are processed transiently into embeddings; passwords and verification codes are excluded. You can change your choice later.
            </small>
          </span>
        </label>
        <ErrorNotice error={task.error} />
        <button className="primary-button" disabled={task.busy}>
          {task.busy ? "Checking details…" : "Sign in"}
        </button>
      </form>
      {session?.demo_mode && (
        <aside
          className="demo-credentials"
          aria-label="Demo account credentials"
        >
          <strong>Demo account credentials</strong>
          <p>Enter the credentials manually and explore the service.</p>
          <dl>
            <div>
              <dt>Login</dt>
              <dd>anna.demo</dd>
            </div>
            <div>
              <dt>Password</dt>
              <dd>bank24</dd>
            </div>
            <div>
              <dt>Sign-in code</dt>
              <dd>1234</dd>
            </div>
          </dl>
        </aside>
      )}
      <Link className="text-button" to="/help?return=%2Flogin">
        I need help signing in
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
        labels={["Sign-in details", "Code verification", "Account access"]}
        ariaLabel="Sign-in steps"
      />
      <PageTitle
        title="Enter the sign-in code"
        intro={`Enter the ${query.data?.code_length ?? 4}-digit sign-in code. Do not share it with anyone.`}
      />
      {query.data?.demo_mode && (
        <p className="notice">
          Demo mode: code <strong>1234</strong>. No SMS is sent.
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
          label="Confirmation code"
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
                ? `Code valid for another ${countdown.expires} s.`
                : "Code expired. Request a new one."
              : "Loading code details…"
          }
        />
        <ErrorNotice error={task.error} />
        <button
          className="primary-button"
          disabled={task.busy || !query.data || !countdown.expires}
        >
          {task.busy ? "Confirming…" : "Confirm sign-in"}
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
          ? `New code in ${countdown.cooldown} s`
          : "Request a new code"}
      </button>
      <Link className="text-button" to="/login">
        Back to sign-in
      </Link>
    </>
  );
}
