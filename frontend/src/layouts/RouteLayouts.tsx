import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { useTask } from "../app/hooks";
import { Bank24Logo, ErrorNotice, Icon } from "../design/components";
import {
  api,
  queryClient,
  sessionOptions,
  updatePermissions,
} from "../services/api";
import { CameraPanel } from "../features/camera/CameraPanel";
import { stopCamera, useCamera } from "../features/camera/store";
import { configureTelemetry } from "../features/telemetry/collector";
import { clearAuthDraft } from "../features/auth/pages";
import { clearTransferDraft } from "../features/transfers/pages";

function Footer() {
  return (
    <footer className="site-footer">
      <span>Bank24 · środowisko demonstracyjne</span>
      <span>
        Rachunki i przelewy są fikcyjne. Żadne prawdziwe środki nie są
        przesyłane.
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
        Przejdź do treści
      </a>
      <header className="auth-header">
        <Link to="/" aria-label="Bank24 — strona główna">
          <Bank24Logo />
        </Link>
        <Link className="auth-back" to="/">
          Strona główna
        </Link>
      </header>
      <main className="auth-main" id="main" tabIndex={-1}>
        <div className="auth-split">
          <section
            className="auth-showcase"
            aria-label="Bank24 — środowisko demonstracyjne"
          >
            <div>
              <p className="eyebrow">BANK24 · DEMONSTRACJA</p>
              <h2>Finanse pod Twoją kontrolą.</h2>
              <p>Sprawdź dane i spokojnie przejdź przez każdy krok operacji.</p>
            </div>
            <span>Fikcyjne konto · bez prawdziwych płatności</span>
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

export function BankLayout() {
  const session = useQuery(sessionOptions);
  const location = useLocation();
  const navigate = useNavigate();
  const task = useTask();
  const camera = useCamera();
  const helpHref =
    "/help?return=" + encodeURIComponent(location.pathname + location.search);
  useEffect(() => configureTelemetry(session.data), [session.data]);
  const showCameraPanel = location.pathname === "/app/transfers/new";
  const stopAndRevoke = () => {
    stopCamera();
    void task.run(async () => {
      await updatePermissions({ camera: false });
    });
  };
  return (
    <div className="bank-shell">
      <a className="skip-link" href="#main">
        Przejdź do treści
      </a>
      <header className="bank-header">
        <Link to="/app" aria-label="Bank24 — konto">
          <Bank24Logo />
        </Link>
        <nav className="bank-nav" aria-label="Nawigacja konta">
          <NavLink to="/app" end>
            <Icon name="home" />
            <span>Konto</span>
          </NavLink>
          <NavLink to="/app/transfers/new">
            <Icon name="transfer" />
            <span>Nowy przelew</span>
          </NavLink>
          <NavLink to="/app/history">
            <Icon name="history" />
            <span>Historia</span>
          </NavLink>
        </nav>
        <div className="bank-header-actions">
          {camera.status === "active" || camera.status === "starting" ? (
            <>
              <span className="camera-live">
                <span aria-hidden="true" />
                Kamera{" "}
                {camera.status === "active" ? "aktywna" : "uruchamia się"}
              </span>
              <button
                className="button button-quiet camera-stop"
                onClick={stopAndRevoke}
              >
                Wyłącz kamerę
              </button>
            </>
          ) : null}
          <Link className="icon-link" aria-label="Pomoc" to={helpHref}>
            <Icon name="help" />
          </Link>
          <button
            className="button button-quiet logout-button"
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                stopCamera();
                configureTelemetry();
                await api("/bank/logout", "POST", {});
                clearAuthDraft();
                clearTransferDraft();
                queryClient.clear();
                navigate("/", { replace: true });
              })
            }
          >
            Wyloguj
          </button>
        </div>
      </header>
      {Boolean(task.error) && (
        <div className="shell-alert">
          <ErrorNotice error={task.error} />
        </div>
      )}
      <div className={"bank-body" + (showCameraPanel ? " has-camera" : "")}>
        <aside className="bank-sidebar">
          <p className="sidebar-label">BANKOWOŚĆ</p>
          <NavLink to="/app" end>
            <Icon name="home" /> Przegląd
          </NavLink>
          <NavLink to="/app/transfers/new">
            <Icon name="transfer" /> Przelewy
          </NavLink>
          <NavLink to="/app/history">
            <Icon name="history" /> Historia operacji
          </NavLink>
          <div className="sidebar-help">
            <strong>Potrzebujesz pomocy?</strong>
            <p>Odpowiedzi na najczęstsze pytania.</p>
            <Link to={helpHref}>
              Centrum pomocy <Icon name="arrow" size={16} />
            </Link>
          </div>
        </aside>
        <main className="bank-main" id="main" tabIndex={-1}>
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
