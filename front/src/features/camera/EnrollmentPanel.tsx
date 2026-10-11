import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorNotice } from "../../design/components";
import {
  cameraProfileStatus,
  deleteCameraProfile,
  enrollCameraSample,
  queryClient,
  startCameraEnrollment,
} from "../../services/api";
import { useCamera } from "./store";

export function EnrollmentPanel() {
  const camera = useCamera();
  const profile = useQuery({ queryKey: ["camera-profile"], queryFn: cameraProfileStatus });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const status = profile.data;
  const elapsed = status?.started_at ? Math.max(0, (now / 1000) - status.started_at) : 0;
  const canEnroll = Boolean(status?.can_enroll);
  if (status && !status.model_available) return null;
  return (
    <section className="camera-enrollment" aria-labelledby="camera-enrollment-title">
      <h2 id="camera-enrollment-title">Profil kamery</h2>
      {profile.isError ? <ErrorNotice error={profile.error} /> : null}
      {status && (
        <>
          <p>
            {status.status === "ready"
              ? `Profil gotowy · wersja ${status.version}. Zatwierdzono ${status.samples} spokojnych próbek.`
              : `Zatwierdzono ${status.samples} z ${status.required} próbek. Profil powstanie po trzeciej zatwierdzonej próbce i zacznie działać od kolejnego logowania.`}
          </p>
          {status.pending > 0 && <p className="field-hint">Próbki oczekujące na niezależne zatwierdzenie operatora: {status.pending}. Nie zmieniają jeszcze profilu.</p>}
          {!canEnroll && <p className="field-hint">Zapis kolejnej próbki wymaga skonfigurowanego operatora.</p>}
          {status.recorded_this_session ? (
            <p className="field-hint">Próbka z tego logowania jest już zapisana. Następną możesz dodać po ponownym logowaniu kodem.</p>
          ) : canEnroll ? (
            <>
              <p className="field-hint">
                Rozpocznij spokojny pomiar z włączoną kamerą i poczekaj co najmniej 40 sekund.
                Każdą próbkę zapisujesz osobno. Po utworzeniu profilu nowa próbka wymaga
                niezależnego zatwierdzenia operatora, zanim zmieni aktywną wersję.
              </p>
              {status.started_at && <p role="status">Pomiar trwa · {Math.floor(elapsed)} s / 40 s</p>}
              <label className="checkbox-row">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
                {status.started_at
                  ? "Potwierdzam, że pomiar przebiegał spokojnie i chcę zapisać tę próbkę."
                  : "Potwierdzam, że chcę rozpocząć osobny pomiar do profilu kamery."}
              </label>
              <button
                className="secondary-button"
                disabled={!confirmed || busy || camera.status !== "active" || Boolean(status.started_at && elapsed < 40)}
                onClick={async () => {
                  setBusy(true);
                  setError(undefined);
                  try {
                    const updated = status.started_at
                      ? await enrollCameraSample()
                      : await startCameraEnrollment();
                    queryClient.setQueryData(["camera-profile"], updated);
                    setConfirmed(false);
                  } catch (cause) {
                    setError(cause);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Przetwarzam…" : status.started_at ? "Zapisz próbkę profilu" : "Rozpocznij pomiar"}
              </button>
              {status.started_at && (
                <button className="text-button" disabled={!confirmed || busy || camera.status !== "active"}
                  onClick={async () => {
                    setBusy(true);
                    setError(undefined);
                    try {
                      queryClient.setQueryData(["camera-profile"], await startCameraEnrollment());
                      setConfirmed(false);
                    } catch (cause) {
                      setError(cause);
                    } finally {
                      setBusy(false);
                    }
                  }}>Rozpocznij od nowa</button>
              )}
              {camera.status !== "active" && <p className="field-hint">Poczekaj na uruchomienie kamery.</p>}
            </>
          ) : null}
          {status.samples > 0 && (
            <button className="text-button" disabled={busy} onClick={async () => {
              if (!window.confirm("Usunąć wszystkie próbki i wersje profilu kamery z tego konta?")) return;
              setBusy(true);
              setError(undefined);
              try {
                queryClient.setQueryData(["camera-profile"], await deleteCameraProfile());
              } catch (cause) {
                setError(cause);
              } finally {
                setBusy(false);
              }
            }}>Usuń profil i próbki</button>
          )}
          {error && <ErrorNotice error={error} />}
        </>
      )}
    </section>
  );
}
