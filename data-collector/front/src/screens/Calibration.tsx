import { useEffect, useState } from "react";
import { useProtocol } from "../protocol/ProtocolContext";

const SECONDS = 20;

export function Calibration() {
  const { startCalibration, finishCalibration, previewRef, recorder, error } = useProtocol();
  const [left, setLeft] = useState(SECONDS);
  const [started, setStarted] = useState(false);

  useEffect(() => {
    if (!started) return;
    const id = window.setInterval(() => {
      setLeft((n) => {
        if (n <= 1) {
          window.clearInterval(id);
          void finishCalibration();
          return 0;
        }
        return n - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [started, finishCalibration]);

  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Camera calibration</h1>
        <p className="lead">
          Sit still facing the camera, with light from the front. Do nothing for 20 seconds to record your resting baseline.
        </p>
        <video ref={previewRef} className="cam-preview" style={{ position: "relative", left: 0, bottom: 0 }} muted playsInline />
        {!started ? (
          <button
            className="btn"
            onClick={() => {
              setStarted(true);
              void startCalibration();
            }}
          >
            Turn on camera and start
          </button>
        ) : (
          <div className="progress-ring">
            <p>Remaining {left} s</p>
            <div className="bar">
              <span style={{ width: `${((SECONDS - left) / SECONDS) * 100}%` }} />
            </div>
            {recorder?.lastError && <p className="error">{recorder.lastError}</p>}
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
