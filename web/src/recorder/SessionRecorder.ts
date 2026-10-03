import { api } from "../api";
import type { Consents, RecEvent } from "../types";
import { startCamera, type CameraHandle, type FaceFrame } from "./cameraRecorder";
import { startClockSync, type ClockOffset } from "./clockSync";
import { collectEnvironment, startMotion, startPings } from "./envCollector";
import { markStage, startEventCapture } from "./eventRecorder";

export class SessionRecorder {
  sessionId: string;
  consents: Consents;
  private events: RecEvent[] = [];
  private faces: FaceFrame[] = [];
  private net: Record<string, unknown>[] = [];
  private stops: Array<() => void> = [];
  private camera: CameraHandle | null = null;
  private flushTimer: number | null = null;
  private closed = false;
  lastError: string | null = null;

  constructor(sessionId: string, consents: Consents) {
    this.sessionId = sessionId;
    this.consents = consents;
  }

  get stream(): MediaStream | null {
    return this.camera?.stream ?? null;
  }

  emit = (e: RecEvent) => {
    if (this.closed) return;
    this.events.push(e);
    if (this.events.length >= 80) void this.flush();
  };

  stage(name: string, kind: "start" | "end") {
    markStage(this.emit, name, kind);
  }

  async start(preview?: HTMLVideoElement | null) {
    if (this.consents.keyboard_mouse) {
      this.stops.push(startEventCapture(this.emit));
    }
    this.stops.push(
      startClockSync((s: ClockOffset) => {
        this.net.push({ type: "clock_sync", ...s });
      }),
    );
    this.stops.push(
      startPings(this.sessionId, (row) => {
        this.net.push(row);
      }),
    );
    if (this.consents.motion) {
      this.stops.push(
        startMotion((row) => {
          this.net.push(row);
        }),
      );
    }
    try {
      const env = await collectEnvironment();
      await api.meta(this.sessionId, { environment: env, camera: null });
      this.net.push({ type: "environment", t_perf: performance.now(), t_epoch: Date.now(), env });
    } catch (err) {
      this.lastError = String(err);
    }
    if (this.consents.video || this.consents.face_pose) {
      try {
        this.camera = await startCamera({
          recordVideo: this.consents.video,
          landmarks: this.consents.face_pose,
          preview,
          onFace: (f) => {
            this.faces.push(f);
            if (this.faces.length >= 20) void this.flush();
          },
          onVideoChunk: (blob, index) => {
            void api.uploadVideo(this.sessionId, index, blob).catch((err) => {
              this.lastError = String(err);
            });
          },
        });
        await api.meta(this.sessionId, {
          camera: {
            settings: this.camera.settings,
            recordVideo: this.consents.video,
            landmarks: this.consents.face_pose,
          },
        });
      } catch (err) {
        this.lastError = "Kamera niedostępna: " + String(err);
      }
    }
    this.flushTimer = window.setInterval(() => void this.flush(), 1200);
    window.addEventListener("pagehide", this.beaconFlush);
  }

  private beaconFlush = () => {
    const rows = this.events.splice(0);
    if (!rows.length) return;
    const blob = new Blob([JSON.stringify({ rows })], { type: "application/json" });
    navigator.sendBeacon(`/api/sessions/${this.sessionId}/events`, blob);
  };

  async flush() {
    const ev = this.events.splice(0);
    const fa = this.faces.splice(0);
    const ne = this.net.splice(0);
    try {
      if (ev.length) await api.events(this.sessionId, ev);
      if (fa.length) await api.face(this.sessionId, fa);
      if (ne.length) await api.net(this.sessionId, ne);
    } catch (err) {
      this.events.unshift(...ev);
      this.faces.unshift(...fa);
      this.net.unshift(...ne);
      this.lastError = String(err);
    }
  }

  async stop() {
    this.closed = true;
    window.removeEventListener("pagehide", this.beaconFlush);
    if (this.flushTimer) window.clearInterval(this.flushTimer);
    for (const s of this.stops) s();
    this.stops = [];
    if (this.camera) await this.camera.stop();
    await this.flush();
  }
}
