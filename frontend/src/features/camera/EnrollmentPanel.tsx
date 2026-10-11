import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ErrorNotice } from "../../design/components";
import {
  cameraProfileStatus,
  checkRisk,
  deleteCameraProfile,
  enrollCameraSample,
  queryClient,
  startCameraEnrollment,
  type RiskCheck,
} from "../../services/api";
import { useCamera } from "./store";

export function EnrollmentPanel() {
  const camera = useCamera();
  const profile = useQuery({ queryKey: ["camera-profile"], queryFn: cameraProfileStatus });
  const risk = useQuery<RiskCheck | null>({ queryKey: ["camera-risk"], queryFn: checkRisk, enabled: false });
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
      <h2 id="camera-enrollment-title">Camera profile</h2>
      {profile.isError ? <ErrorNotice error={profile.error} /> : null}
      {status && (
        <>
          <p>
            {status.status === "ready"
              ? `Profile ready · version ${status.version}. ${status.samples} calm samples approved.`
              : `${status.samples} of ${status.required} samples approved. The profile will be created after the third approved sample and take effect at the next sign-in.`}
          </p>
          {status.activates_next_sign_in && (
            <p role="status" className="notice">
              Your samples are saved. Sign out and sign in again to use the updated profile. This recording is kept separate from assessment data.
            </p>
          )}
          {status.status === "ready" && !status.activates_next_sign_in && (
            <p role="status">
              {camera.status !== "active"
                ? "Camera score unavailable. Turn on the camera to collect assessment data."
                : risk.data?.status === "ok" && risk.data.account_takeover_risk !== null && now - risk.dataUpdatedAt < 20_000
                  ? `Experimental owner profile mismatch: ${risk.data.account_takeover_risk}/100. This is not a fraud probability.`
                  : `Camera score unavailable. ${risk.data?.reason || "Waiting for a current assessment."}`}
            </p>
          )}
          {risk.data?.status === "ok" && now - risk.dataUpdatedAt < 20_000 && Boolean(risk.data.available_signals?.length) && (
            <p className="field-hint">Inputs in use: {risk.data.available_signals?.map(signal => ({
              keyboard: "typing rhythm", mouse: "mouse movement", camera_pulse: "camera pulse",
              camera_face: "expression and posture", context: "form interaction",
              network: "connection timings", device: "device reference",
            }[signal] || signal)).join(", ")}.</p>
          )}
          {status.pending > 0 && <p className="field-hint">Samples awaiting independent operator approval: {status.pending}. They do not change the profile yet.</p>}
          {!canEnroll && <p className="field-hint">Saving another sample requires a configured operator.</p>}
          {status.recorded_this_session ? (
            <p className="field-hint">A sample from this sign-in is already saved. Sign in again with a code to add another.</p>
          ) : canEnroll ? (
            <>
              <p className="field-hint">
                Start a calm recording with the camera on and wait at least 40 seconds. With optional usage metadata enabled, normal mouse movement and typing in a transfer field also build your reference; no transfer needs to be submitted. Save each sample separately. Once a profile exists, new samples require independent operator approval before changing the active version.
              </p>
              {status.started_at && <p role="status">Recording in progress · {Math.floor(elapsed)} s / 40 s</p>}
              <label className="checkbox-row">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
                {status.started_at
                  ? "I confirm that the recording was calm and I want to save this sample."
                  : "I confirm that I want to start a separate recording for the camera profile."}
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
                {busy ? "Processing…" : status.started_at ? "Save profile sample" : "Start recording"}
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
                  }}>Start again</button>
              )}
              {camera.status !== "active" && <p className="field-hint">Wait for the camera to start.</p>}
            </>
          ) : null}
          {status.samples > 0 && (
            <button className="text-button" disabled={busy} onClick={async () => {
              if (!window.confirm("Delete all camera profile samples and versions from this account?")) return;
              setBusy(true);
              setError(undefined);
              try {
                queryClient.setQueryData(["camera-profile"], await deleteCameraProfile());
                queryClient.setQueryData(["camera-risk"], null);
              } catch (cause) {
                setError(cause);
              } finally {
                setBusy(false);
              }
            }}>Delete profile and samples</button>
          )}
          {error && <ErrorNotice error={error} />}
        </>
      )}
    </section>
  );
}
