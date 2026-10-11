import { useSyncExternalStore } from "react";
import { api } from "../../services/api";

interface Landmark {
  index: number;
  x: number;
  y: number;
  z: number;
  visibility?: number;
  presence?: number;
}
interface Measurement {
  session_id: string;
  timestamp: number;
  status: string;
  heart_rate_bpm: number | null;
  heart_rate_stale: boolean;
  heart_rate_updated_at: number | null;
  face_detected: boolean;
  sampling_fps: number | null;
  window_seconds: number | null;
  landmarks: { pose: Landmark[]; face: Landmark[] } | null;
  landmarks_timestamp_ms: number | null;
  frame_width: number | null;
  frame_height: number | null;
  error?: string;
}
interface CameraState {
  status: "off" | "starting" | "active" | "error";
  stream: MediaStream | null;
  remote: MediaStream | null;
  preview: string | null;
  measurement: Measurement | null;
  received: number;
  error: string;
  stale: boolean;
}
let state: CameraState = {
  status: "off",
  stream: null,
  remote: null,
  preview: null,
  measurement: null,
  received: 0,
  error: "",
  stale: false,
};
const listeners = new Set<() => void>();
let generation = 0;
let captureStream: MediaStream | null = null;
let captureVideo: HTMLVideoElement | null = null;
let sessionId: string | null = null;
let peer: RTCPeerConnection | null = null;
let poller: number | null = null;

function update(next: Partial<CameraState>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}
export function useCamera() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
  );
}
export function stopCamera(message = "") {
  generation++;
  captureStream?.getTracks().forEach((track) => track.stop());
  captureStream = null;
  if (captureVideo) captureVideo.srcObject = null;
  captureVideo = null;
  peer?.close();
  peer = null;
  if (poller !== null) clearInterval(poller);
  poller = null;
  const oldId = sessionId;
  sessionId = null;
  if (oldId)
    void api((oldId.startsWith("frame-") ? "/frames/sessions/" : "/sessions/") + oldId, "DELETE").catch(() => {});
  update({
    status: message ? "error" : "off",
    stream: null,
    remote: null,
    preview: null,
    measurement: null,
    received: 0,
    error: message,
    stale: false,
  });
}

function frameBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob ? resolve(blob) : reject(new Error("Could not encode the camera image.")),
      "image/jpeg",
      0.7,
    );
  });
}

function applyMeasurement(measurement: Measurement, extra: Partial<CameraState> = {}) {
  if ((state.measurement?.timestamp || 0) > measurement.timestamp) return;
  const stale =
    !Number.isFinite(measurement.timestamp) || Date.now() / 1000 - measurement.timestamp > 5;
  update({ status: "active", measurement, received: Date.now(), stale, error: "", ...extra });
}

function waitForIce(pc: RTCPeerConnection) {
  return new Promise<void>((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const timer = setTimeout(resolve, 4000);
    pc.addEventListener("icegatheringstatechange", () => {
      if (pc.iceGatheringState === "complete") {
        clearTimeout(timer);
        resolve();
      }
    });
  });
}

// Real-time path: browser -> TURN (TCP) -> worker, annotated video returned on the same peer connection.
async function startWebRtc(stream: MediaStream, token: number): Promise<boolean> {
  const ice = await api<{ iceServers: RTCIceServer[]; iceTransportPolicy: RTCIceTransportPolicy }>(
    "/webrtc/ice-servers",
  );
  if (!ice.iceServers.length || token !== generation) return false;
  const pc = new RTCPeerConnection({ iceServers: ice.iceServers, iceTransportPolicy: ice.iceTransportPolicy });
  peer = pc;
  stream.getVideoTracks().forEach((track) => pc.addTransceiver(track, { direction: "sendrecv" }));
  const remote = new Promise<MediaStream>((resolve) => {
    pc.ontrack = (event) => resolve(event.streams[0] || new MediaStream([event.track]));
  });
  await pc.setLocalDescription(await pc.createOffer());
  await waitForIce(pc);
  if (token !== generation) return false;
  if (!pc.localDescription?.sdp.includes(" relay ")) throw new Error("TURN unavailable");
  const answer = await api<{ sdp: string; type: RTCSdpType; session_id: string }>("/webrtc/offer", "POST", {
    sdp: pc.localDescription.sdp,
    type: "offer",
  });
  sessionId = answer.session_id;
  await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
  const connected = await new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => resolve(false), 12000);
    const check = () => {
      if (pc.connectionState === "connected") {
        clearTimeout(timer);
        resolve(true);
      } else if (pc.connectionState === "failed" || pc.connectionState === "closed") {
        clearTimeout(timer);
        resolve(false);
      }
    };
    pc.addEventListener("connectionstatechange", check);
    check();
  });
  if (!connected || token !== generation) return false;
  update({ remote: await remote, status: "active" });
  pc.addEventListener("connectionstatechange", () => {
    if (token === generation && pc.connectionState === "failed")
      stopCamera("The WebRTC connection was interrupted. Restart the camera.");
  });
  const id = answer.session_id;
  poller = window.setInterval(async () => {
    try {
      const measurement = await api<Measurement>("/sessions/" + id + "/output");
      if (token === generation) applyMeasurement(measurement);
    } catch {
      /* transient; the video keeps flowing */
    }
  }, 1000);
  return true;
}

export async function startCamera() {
  if (state.status === "starting" || state.status === "active") return;
  stopCamera();
  const token = generation;
  update({ status: "starting" });
  let stream: MediaStream | null = null;
  let cameraId: string | null = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    if (token !== generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    captureStream = stream;
    update({ stream });
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    captureVideo = video;
    stream.getTracks().forEach((track) => {
      track.onended = () => {
        if (token === generation)
          stopCamera("The camera was disconnected. You can restart it.");
      };
    });
    await video.play();
    if (token !== generation) return;
    try {
      if (await startWebRtc(stream, token)) return;
    } catch (error) {
      console.warn("WebRTC unavailable, falling back to HTTPS frames", error);
    }
    if (token !== generation) return;
    peer?.close();
    peer = null;
    if (sessionId) void api("/sessions/" + sessionId, "DELETE").catch(() => {});
    sessionId = null;
    const answer = await api<{ session_id: string }>("/frames/sessions", "POST");
    cameraId = answer.session_id;
    if (token !== generation) {
      void api("/frames/sessions/" + cameraId, "DELETE").catch(() => {});
      return;
    }
    sessionId = cameraId;
    const send = async () => {
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      if (!context) {
        stopCamera("Could not prepare the camera image.");
        return;
      }
      while (token === generation && sessionId) {
        const frameStarted = performance.now();
        try {
          if (!video.videoWidth || !video.videoHeight)
            throw new Error("The camera is not providing video frames.");
          const scale = Math.min(1, 640 / video.videoWidth, 480 / video.videoHeight);
          canvas.width = Math.round(video.videoWidth * scale);
          canvas.height = Math.round(video.videoHeight * scale);
          context.drawImage(video, 0, 0, canvas.width, canvas.height);
          const blob = await frameBlob(canvas);
          if (token !== generation) return;
          const result = await api<{ measurement: Measurement; image: string }>(
            "/frames/sessions/" + sessionId + "/frame", "POST", blob,
          );
          if (token !== generation) return;
          applyMeasurement(result.measurement, { preview: "data:image/jpeg;base64," + result.image });
          // Four concurrent senders share a budget of about 30 frames per second.
          await new Promise((resolve) => setTimeout(resolve, Math.max(0, 133 - (performance.now() - frameStarted))));
        } catch (error) {
          if (token === generation)
            stopCamera(error instanceof Error ? error.message : "Could not send the camera frame.");
          return;
        }
      }
    };
    for (let i = 0; i < 4; i++) void send();
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    if (cameraId && cameraId !== sessionId)
      void api("/frames/sessions/" + cameraId, "DELETE").catch(() => {});
    if (token === generation)
      stopCamera(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Camera permission denied. Change your browser permissions or continue without it."
          : error instanceof Error
            ? error.message
            : "Could not start the camera.",
      );
  }
}
window.addEventListener("pagehide", () => stopCamera());
window.addEventListener("bank24:expired", () => stopCamera());
