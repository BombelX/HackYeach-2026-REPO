import { useEffect, useRef, useState } from "react";
import { CameraIcon, ErrorNotice } from "../../design/components";
import { updatePermissions } from "../../services/api";
import { startCamera, stopCamera, useCamera } from "./store";

const statuses: Record<string, string> = {
  waiting: "Waiting for video",
  preview: "Preview · no pulse estimation",
  warming_up: "Collecting samples",
  measuring: "Video analysis",
  stale: "Pulse needs updating",
  error: "Analysis error",
  ended: "Ended",
  closed: "Closed",
};
function formatTimestamp(value: number | null | undefined) {
  return value == null
    ? "No measurement"
    : new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(value * 1000);
}
function formatMonotonicTimestamp(value: number | null | undefined) {
  return value == null ? "No measurement" : `${Math.round(value)} ms`;
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
    if (video.current) video.current.srcObject = camera.remote || camera.stream;
  }, [camera.remote, camera.stream]);
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
    value == null ? "No measurement" : value + suffix;
  return (
    <aside className={"camera-panel" + (bank ? " camera-panel-bank" : "")}>
      <details className="camera-body" ref={container}>
        <summary>Camera preview and parameters</summary>
        <div className="camera-heading">
          <CameraIcon />
          <h2>Camera</h2>
          <span className="camera-label">{bank ? "Active since sign-in" : "Optional"}</span>
        </div>
        <p className="camera-description">
          {bank
            ? "Video is analyzed throughout the session to compare behavior with the account owner profile."
            : "Video helps collect research data. The camera does not verify your identity."}
        </p>
        <div className="camera-preview">
          <video
            ref={video}
            autoPlay
            muted
            playsInline
            hidden={!camera.stream || !!camera.preview}
          />
          {camera.preview && (
            <img src={camera.preview} alt="Video with analysis points from the server" />
          )}
          {!camera.stream && (
            <div className="camera-placeholder">
              <CameraIcon />
              <strong>{bank ? "Starting camera…" : "Preview off"}</strong>
              <span>{bank ? "Allow camera access in your browser" : "Start when you are ready"}</span>
            </div>
          )}
          <div className="preview-caption">
            <span role="status" aria-live="polite" aria-atomic="true">
              {camera.status === "active"
                ? "Analyzed preview from the server"
                : camera.status === "starting"
                  ? "Connecting…"
                  : "Camera off"}
            </span>
            <span>No audio</span>
          </div>
        </div>
        <div className="camera-actions">
          {bank ? (
            camera.status === "error" && (
              <button className="secondary-button" onClick={() => void startCamera()}>
                Restart camera
              </button>
            )
          ) : camera.status === "off" || camera.status === "error" ? (
            <button
              className="secondary-button"
              onClick={() =>
                enabled ? void startCamera() : setConsentOpen(true)
              }
            >
              Turn on camera
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
              Turn off camera
            </button>
          )}
        </div>
        {!enabled && !bank && (
          <p className="field-hint">
            The camera is off. Consent is optional and does not affect account access.
          </p>
        )}
        {consentOpen && !bank && (
          <div
            className="camera-consent"
            role="group"
            aria-label="Camera consent"
          >
            <p>
              When enabled, video is sent to the local analysis server. We do not save recordings or audio. Estimates are experimental.
            </p>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
              />
              I consent to video transmission and analysis.
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
              Start camera
            </button>
            <button
              className="text-button"
              onClick={() => setConsentOpen(false)}
            >
              Cancel
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
          <summary>Session parameters</summary>
          <div className="parameter-content">
            {camera.stale && (
              <p className="notice">
                Measurement is stale. Waiting for new data.
              </p>
            )}
            <dl className="metric-list">
              <div>
                <dt>Estimated pulse</dt>
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
                <dt>Face in frame</dt>
                <dd>
                  {result
                    ? result.face_detected
                      ? "Detected"
                      : "Not detected"
                    : "No data"}
                </dd>
              </div>
              <div>
                <dt>Body landmarks</dt>
                <dd>{display(result?.landmarks?.pose.length)}</dd>
              </div>
              <div>
                <dt>Face landmarks</dt>
                <dd>{display(result?.landmarks?.face.length)}</dd>
              </div>
              <div>
                <dt>Analysis status</dt>
                <dd>
                  {result
                    ? statuses[result.status] || "Unsupported status"
                    : "No current data"}
                </dd>
              </div>
              <div>
                <dt>Pulse freshness</dt>
                <dd>
                  {result
                    ? result.heart_rate_bpm == null
                      ? "No measurement"
                      : result.heart_rate_stale
                        ? "Stale"
                        : "Current"
                    : "No data"}
                </dd>
              </div>
              {result?.error && (
                <div>
                  <dt>Error details</dt>
                  <dd>{result.error}</dd>
                </div>
              )}
            </dl>
            <details>
              <summary>Measurement details</summary>
              <dl className="metric-list">
                <div>
                  <dt>Sampling</dt>
                  <dd>{display(result?.sampling_fps?.toFixed(1), " FPS")}</dd>
                </div>
                <div>
                  <dt>Window</dt>
                  <dd>{display(result?.window_seconds?.toFixed(1), " s")}</dd>
                </div>
                <div>
                  <dt>Last update</dt>
                  <dd>{formatTimestamp(result?.timestamp)}</dd>
                </div>
                <div>
                  <dt>Last pulse update</dt>
                  <dd>{formatTimestamp(result?.heart_rate_updated_at)}</dd>
                </div>
                <div>
                  <dt>Session ID</dt>
                  <dd>{display(result?.session_id)}</dd>
                </div>
                <div>
                  <dt>Analyzed frame size</dt>
                  <dd>
                    {result?.frame_width == null || result.frame_height == null
                      ? "No measurement"
                      : `${result.frame_width} × ${result.frame_height} px`}
                  </dd>
                </div>
                <div>
                  <dt>Model landmark timestamp</dt>
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
                <summary>All landmark coordinates</summary>
                {landmarksOpen && (
                  <pre>
                    {result?.landmarks
                      ? JSON.stringify(result.landmarks, null, 2)
                      : "No landmarks in the current measurement."}
                  </pre>
                )}
              </details>
            </details>
          </div>
        </details>
        <div className="camera-guidance">
          <h3>Prepare the camera</h3>
          <p>
            Place the camera at eye level. Use even lighting and keep your face visible.
          </p>
          <p>
            A missing measurement does not mean low risk. The camera does not block account access.
          </p>
        </div>
      </details>
    </aside>
  );
}
