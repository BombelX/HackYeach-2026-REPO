import { useEffect, useState } from "react";
import { useProtocol } from "../protocol/ProtocolContext";

const SECONDS = 60;

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
        <h1>Kalibracja kamery</h1>
        <p className="lead">
          Siedź spokojnie, twarzą do kamery, w świetle z przodu. Przez minutę nic nie rób — to Twoja norma spoczynkowa.
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
            Włącz kamerę i zacznij
          </button>
        ) : (
          <div className="progress-ring">
            <p>Zostało {left} s</p>
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
