import { useEffect, useRef, useState } from "react";
import { CameraIcon, ErrorNotice } from "../../design/components";
import { updatePermissions } from "../../services/api";
import { startCamera, stopCamera, useCamera } from "./store";

const statuses: Record<string, string> = {
  waiting: "Oczekiwanie na obraz",
  preview: "Podgląd · analiza wyłączona",
  warming_up: "Zbieranie próbek",
  measuring: "Analiza obrazu",
  stale: "Puls wymaga odświeżenia",
  error: "Błąd analizy",
  ended: "Zakończona",
  closed: "Zamknięta",
};
function formatTimestamp(value: number | null | undefined) {
  return value == null
    ? "Brak pomiaru"
    : new Intl.DateTimeFormat("pl-PL", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(value * 1000);
}
function formatMonotonicTimestamp(value: number | null | undefined) {
  return value == null ? "Brak pomiaru" : `${Math.round(value)} ms`;
}
export function CameraPanel({
  enabled,
  bank,
}: {
  enabled: boolean;
  bank: boolean;
}) {
  const camera = useCamera();
  const video = useRef<HTMLVideoElement>(null);
  const [consentOpen, setConsentOpen] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [landmarksOpen, setLandmarksOpen] = useState(false);
  const [permissionError, setPermissionError] = useState<unknown>();
  const container = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (video.current) video.current.srcObject = camera.stream;
  }, [camera.stream]);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const resize = () => {
      if (container.current) container.current.open = media.matches;
    };
    resize();
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);
  const result = camera.stale ? null : camera.measurement;
  const display = (value: string | number | null | undefined, suffix = "") =>
    value == null ? "Brak pomiaru" : value + suffix;
  return (
    <aside className={"camera-panel" + (bank ? " camera-panel-bank" : "")}>
      <details className="camera-body" ref={container}>
        <summary>Podgląd kamery i parametry</summary>
        <div className="camera-heading">
          <CameraIcon />
          <h2>Kamera</h2>
          <span className="camera-label">Opcjonalna</span>
        </div>
        <p className="camera-description">
          Obraz pomaga zbierać dane do badania. Kamera nie potwierdza Twojej
          tożsamości.
        </p>
        <div className="camera-preview">
          <video
            ref={video}
            autoPlay
            muted
            playsInline
            hidden={!camera.stream}
          />
          {!camera.stream && (
            <div className="camera-placeholder">
              <CameraIcon />
              <strong>Podgląd wyłączony</strong>
              <span>Uruchom, gdy będziesz gotowy</span>
            </div>
          )}
          <div className="preview-caption">
            <span role="status" aria-live="polite" aria-atomic="true">
              {camera.status === "active"
                ? "Analizowany podgląd z serwera"
                : camera.status === "starting"
                  ? "Łączenie…"
                  : "Kamera wyłączona"}
            </span>
            <span>Bez dźwięku</span>
          </div>
        </div>
        <div className="camera-actions">
          {camera.status === "off" || camera.status === "error" ? (
            <button
              className="secondary-button"
              onClick={() =>
                enabled ? void startCamera() : setConsentOpen(true)
              }
            >
              Włącz kamerę
            </button>
          ) : (
            <button
              className="secondary-button"
              onClick={async () => {
                stopCamera();
                setConsentOpen(false);
                try {
                  await updatePermissions({ camera: false });
                } catch (error) {
                  setPermissionError(error);
                }
              }}
            >
              Wyłącz kamerę
            </button>
          )}
        </div>
        {!enabled && (
          <p className="field-hint">
            Kamera jest wyłączona. Zgoda jest opcjonalna i nie wpływa na dostęp
            do konta.
          </p>
        )}
        {consentOpen && (
          <div
            className="camera-consent"
            role="group"
            aria-label="Zgoda na kamerę"
          >
            <p>
              Po włączeniu obraz jest przesyłany do lokalnego serwera analizy.
              Nie zapisujemy nagrań ani dźwięku. Estymacje są eksperymentalne.
            </p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
              />
              Zgadzam się na transmisję i analizę obrazu.
            </label>
            <button
              className="primary-button"
              disabled={!agreed || camera.status === "starting"}
              onClick={async () => {
                try {
                  await updatePermissions({ camera: true });
                  setPermissionError(undefined);
                  setConsentOpen(false);
                  await startCamera();
                } catch (error) {
                  setPermissionError(error);
                }
              }}
            >
              Uruchom kamerę
            </button>
            <button
              className="text-button"
              onClick={() => setConsentOpen(false)}
            >
              Anuluj
            </button>
          </div>
        )}
        <ErrorNotice error={permissionError} />
        {camera.error && (
          <p role="status" className="field-error">
            {camera.error}
          </p>
        )}
        <details className="parameters">
          <summary>Parametry sesji</summary>
          <div className="parameter-content">
            {camera.stale && (
              <p className="notice">
                Pomiar nieaktualny. Czekamy na nowe dane.
              </p>
            )}
            <dl className="metric-list">
              <div>
                <dt>Estymowany puls</dt>
                <dd>
                  {display(
                    result?.heart_rate_bpm == null
                      ? null
                      : Math.round(result.heart_rate_bpm),
                    " BPM",
                  )}
                </dd>
              </div>
              <div>
                <dt>Twarz w kadrze</dt>
                <dd>
                  {result
                    ? result.face_detected
                      ? "Wykryta"
                      : "Niewykryta"
                    : "Brak danych"}
                </dd>
              </div>
              <div>
                <dt>Punkty sylwetki</dt>
                <dd>{display(result?.landmarks?.pose.length)}</dd>
              </div>
              <div>
                <dt>Punkty twarzy</dt>
                <dd>{display(result?.landmarks?.face.length)}</dd>
              </div>
              <div>
                <dt>Stan analizy</dt>
                <dd>
                  {result
                    ? statuses[result.status] || "Nieobsługiwany stan"
                    : "Brak aktualnych danych"}
                </dd>
              </div>
              <div>
                <dt>Aktualność pulsu</dt>
                <dd>
                  {result
                    ? result.heart_rate_bpm == null
                      ? "Brak pomiaru"
                      : result.heart_rate_stale
                        ? "Nieaktualny"
                        : "Aktualny"
                    : "Brak danych"}
                </dd>
              </div>
              {result?.error && (
                <div>
                  <dt>Szczegół błędu</dt>
                  <dd>{result.error}</dd>
                </div>
              )}
            </dl>
            <details>
              <summary>Szczegóły pomiaru</summary>
              <dl className="metric-list">
                <div>
                  <dt>Próbkowanie</dt>
                  <dd>{display(result?.sampling_fps?.toFixed(1), " FPS")}</dd>
                </div>
                <div>
                  <dt>Okno</dt>
                  <dd>{display(result?.window_seconds?.toFixed(1), " s")}</dd>
                </div>
                <div>
                  <dt>Ostatnia aktualizacja</dt>
                  <dd>{formatTimestamp(result?.timestamp)}</dd>
                </div>
                <div>
                  <dt>Ostatnia aktualizacja pulsu</dt>
                  <dd>{formatTimestamp(result?.heart_rate_updated_at)}</dd>
                </div>
                <div>
                  <dt>Identyfikator sesji</dt>
                  <dd>{display(result?.session_id)}</dd>
                </div>
                <div>
                  <dt>Rozmiar analizowanej klatki</dt>
                  <dd>
                    {result?.frame_width == null || result.frame_height == null
                      ? "Brak pomiaru"
                      : `${result.frame_width} × ${result.frame_height} px`}
                  </dd>
                </div>
                <div>
                  <dt>Czas landmarków modelu</dt>
                  <dd>
                    {formatMonotonicTimestamp(result?.landmarks_timestamp_ms)}
                  </dd>
                </div>
              </dl>
              <details
                className="landmark-data"
                open={landmarksOpen}
                onToggle={(event) =>
                  setLandmarksOpen(
                    (event.currentTarget as HTMLDetailsElement).open,
                  )
                }
              >
                <summary>Wszystkie współrzędne landmarków</summary>
                {landmarksOpen && (
                  <pre>
                    {result?.landmarks
                      ? JSON.stringify(result.landmarks, null, 2)
                      : "Brak landmarków w aktualnym pomiarze."}
                  </pre>
                )}
              </details>
            </details>
          </div>
        </details>
        <div className="camera-guidance">
          <h3>Przygotuj podgląd</h3>
          <p>
            Ustaw kamerę na wysokości oczu. Zadbaj o równomierne światło i
            widoczność twarzy.
          </p>
          <p>
            Brak pomiaru nie oznacza niskiego ryzyka. Kamera nie blokuje
            korzystania z konta.
          </p>
        </div>
      </details>
    </aside>
  );
}
