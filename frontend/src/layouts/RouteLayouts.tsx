import { voluntaryLogout } from "../services/api";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { useTask } from "../app/hooks";
import { appPathname } from "../app/path";
import { Bank24Logo, ErrorNotice, Icon } from "../design/components";
import { api, checkRisk, queryClient, sessionOptions } from "../services/api";
import { CameraPanel } from "../features/camera/CameraPanel";
import { EnrollmentPanel } from "../features/camera/EnrollmentPanel";
import { startCamera, stopCamera, useCamera } from "../features/camera/store";
import { configureTelemetry } from "../features/telemetry/collector";
import { clearAuthDraft } from "../features/auth/pages";
import { clearTransferDraft } from "../features/transfers/pages";

function Footer() {
  return (
    <footer className="site-footer">
      <span>Bank24 · demonstration environment</span>
      <span>
        Accounts and transfers are fictional. No real money is transferred.
      </span>
    </footer>
  );
}

export function AuthLayout() {
  const session = useQuery(sessionOptions);
  useEffect(() => configureTelemetry(session.data), [session.data]);
  return (
    <div className="auth-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="auth-header">
        <Link to="/" aria-label="Bank24 — home page">
          <Bank24Logo />
        </Link>
        <Link className="auth-back" to="/">
          Home page
        </Link>
      </header>
      <main className="auth-main" id="main" tabIndex={-1}>
        <div className="auth-split">
          <section
            className="auth-showcase"
            aria-label="Bank24 — demonstration environment"
          >
            <div>
              <p className="eyebrow">BANK24 · DEMO</p>
              <h2>Your finances under control.</h2>
              <p>Check the details and take your time through each step.</p>
            </div>
            <span>Fictional account · no real payments</span>
          </section>
          <div className="auth-card">
            <Outlet />
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}

const RISK_FIRST_CHECK_MS = 4_000;
const RISK_CHECK_MS = 8_000;
const LOGOUT_AFTER_ALERT_S = 15;

/** While signed in, ask the server's camera model whether the user still matches the owner profile. */
function useRiskMonitor(active: boolean) {
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let timer = 0;
    const tick = async () => {
      let delay = RISK_CHECK_MS;
      try {
        const result = await checkRisk();
        if (stopped) return;
        queryClient.setQueryData(["camera-risk"], result);
        // A pending alarm tells us when it takes effect; check right after that moment.
        if (result.retry_after)
          delay = Math.min(delay, result.retry_after * 1000 + 300);
      } catch {
        if (!stopped) queryClient.setQueryData(["camera-risk"], null);
        // anomaly_detected arrives as the bank24:anomaly event; other errors retry later
      }
      if (!stopped) timer = window.setTimeout(tick, delay);
    };
    timer = window.setTimeout(tick, RISK_FIRST_CHECK_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      queryClient.setQueryData(["camera-risk"], null);
    };
  }, [active]);
}

function AnomalyTicker({ message }: { message: string }) {
  const text = `⚠ UWAGA: ${message} ⚠`;
  return (
    <div className="anomaly-ticker" aria-hidden="true">
      <div className="anomaly-ticker-track" aria-hidden="true">
        <span>{text}</span>
        <span>{text}</span>
      </div>
    </div>
  );
}

function AnomalyLock({
  message,
  seconds,
}: {
  message: string;
  seconds: number;
}) {
  return (
    <div
      className="anomaly-lock"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="anomaly-title"
      aria-describedby="anomaly-message"
    >
      <div className="anomaly-lock-card">
        <h2 id="anomaly-title">Unusual behavior detected</h2>
        <p id="anomaly-message">{message}</p>
        <p className="anomaly-lock-count" aria-live="polite">
          The app is locked. Signing out in {seconds} s.
        </p>
      </div>
    </div>
  );
}

export function BankLayout() {
  const session = useQuery(sessionOptions);
  const location = useLocation();
  const navigate = useNavigate();
  const task = useTask();
  const camera = useCamera();
  const helpHref =
    "/help?return=" +
    encodeURIComponent(appPathname(location.pathname) + location.search);
  useEffect(() => configureTelemetry(session.data), [session.data]);
  const showCameraPanel =
    appPathname(location.pathname) === "/app/transfers/new";
  const [anomaly, setAnomaly] = useState("");
  const [leaving, setLeaving] = useState(false);
  const [countdown, setCountdown] = useState(LOGOUT_AFTER_ALERT_S);
  const signedIn = !!session.data?.authenticated;
  useEffect(() => { if (signedIn) voluntaryLogout.active = false; }, [signedIn]);
  useRiskMonitor(signedIn && !anomaly);
  useEffect(() => {
    // The camera runs for the whole signed-in session; consent is granted at login.
    if (
      signedIn &&
      session.data?.camera &&
      camera.status === "off" &&
      !anomaly &&
      !leaving
    )
      void startCamera();
  }, [signedIn, session.data?.camera, camera.status, anomaly, leaving]);
  useEffect(() => {
    const onAnomaly = (event: Event) => {
      // The server has already ended the session; stop data entry and drop everything typed.
      stopCamera();
      configureTelemetry();
      clearAuthDraft();
      clearTransferDraft();
      (document.activeElement as HTMLElement | null)?.blur();
      setCountdown(LOGOUT_AFTER_ALERT_S);
      setAnomaly(
        String(
          (event as CustomEvent).detail || "A profile mismatch was detected.",
        ),
      );
    };
    window.addEventListener("bank24:anomaly", onAnomaly);
    return () => window.removeEventListener("bank24:anomaly", onAnomaly);
  }, []);
  useEffect(() => {
    if (!anomaly) return;
    if (countdown <= 0) {
      // Full reload to the start page so no signed-in state survives in memory.
      queryClient.clear();
      window.location.replace(import.meta.env.BASE_URL);
      return;
    }
    const timer = window.setTimeout(
      () => setCountdown((value) => value - 1),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [anomaly, countdown]);
  return (
    <div className="bank-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="bank-header">
        <Link to="/app" aria-label="Bank24 — account">
          <Bank24Logo />
        </Link>
        <nav className="bank-nav" aria-label="Account navigation">
          <NavLink to="/app" end>
            <Icon name="home" />
            <span>Account</span>
          </NavLink>
          <NavLink to="/app/transfers/new">
            <Icon name="transfer" />
            <span>New transfer</span>
          </NavLink>
          <NavLink to="/app/history">
            <Icon name="history" />
            <span>History</span>
          </NavLink>
        </nav>
        <div className="bank-header-actions">
          {camera.status === "active" || camera.status === "starting" ? (
            <>
              <span className="camera-live">
                <span aria-hidden="true" />
                Camera{" "}
                {camera.status === "active" ? "active" : "starting"}
              </span>
            </>
          ) : null}
          <Link className="icon-link" aria-label="Help" to={helpHref}>
            <Icon name="help" />
          </Link>
          <button
            className="button button-quiet logout-button"
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                voluntaryLogout.active = true;
                setLeaving(true);
                stopCamera();
                configureTelemetry();
                try {
                  await api("/bank/logout", "POST", {});
                } catch (error) {
                  voluntaryLogout.active = false;
                  setLeaving(false);
                  throw error;
                }
                clearAuthDraft();
                clearTransferDraft();
                queryClient.clear();
                navigate("/", { replace: true });
              })
            }
          >
            Sign out
          </button>
        </div>
      </header>
      {Boolean(task.error) && (
        <div className="shell-alert">
          <ErrorNotice error={task.error} />
        </div>
      )}
      {anomaly && <AnomalyTicker message={anomaly} />}
      {anomaly && <AnomalyLock message={anomaly} seconds={countdown} />}
      <div
        className={"bank-body" + (showCameraPanel ? " has-camera" : "")}
        inert={anomaly ? true : undefined}
      >
        <aside className="bank-sidebar">
          <p className="sidebar-label">BANKING</p>
          <NavLink to="/app" end>
            <Icon name="home" /> Overview
          </NavLink>
          <NavLink to="/app/transfers/new">
            <Icon name="transfer" /> Transfers
          </NavLink>
          <NavLink to="/app/history">
            <Icon name="history" /> Transaction history
          </NavLink>
          <div className="sidebar-help">
            <strong>Need help?</strong>
            <p>Answers to frequently asked questions.</p>
            <Link to={helpHref}>
              Help center <Icon name="arrow" size={16} />
            </Link>
          </div>
        </aside>
        <main className="bank-main" id="main" tabIndex={-1}>
          <EnrollmentPanel />
          <Outlet />
        </main>
        {showCameraPanel && (
          <CameraPanel enabled={!!session.data?.camera} bank />
        )}
      </div>
      <Footer />
    </div>
  );
}
