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
  measurement: Measurement | null;
  received: number;
  error: string;
  stale: boolean;
}
let state: CameraState = {
  status: "off",
  stream: null,
  measurement: null,
  received: 0,
  error: "",
  stale: false,
};
const listeners = new Set<() => void>();
let generation = 0;
let peer: RTCPeerConnection | null = null;
let captureStream: MediaStream | null = null;
let sessionId: string | null = null;
let poll: ReturnType<typeof setTimeout> | undefined;
function update(next: Partial<CameraState>) {
  state = { ...state, ...next };
  listeners.forEach((listener) => listener());
}
export function useCamera() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => state,
  );
}
export function stopCamera(message = "") {
  generation++;
  if (poll) clearTimeout(poll);
  captureStream?.getTracks().forEach((track) => track.stop());
  captureStream = null;
  state.stream?.getTracks().forEach((track) => track.stop());
  peer?.close();
  peer = null;
  const oldId = sessionId;
  sessionId = null;
  if (oldId) void api("/sessions/" + oldId, "DELETE").catch(() => {});
  update({
    status: message ? "error" : "off",
    stream: null,
    measurement: null,
    received: 0,
    error: message,
    stale: false,
  });
}
async function gather(connection: RTCPeerConnection) {
  if (connection.iceGatheringState === "complete") return;
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      connection.removeEventListener("icegatheringstatechange", check);
      reject(new Error("Nie udało się zestawić połączenia kamery."));
    }, 12_000);
    const check = () => {
      if (connection.iceGatheringState === "complete") {
        clearTimeout(timeout);
        connection.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    connection.addEventListener("icegatheringstatechange", check);
  });
}
export async function startCamera() {
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
    update({ stream });
    captureStream = stream;
    const connection = new RTCPeerConnection({ iceServers: [] });
    peer = connection;
    connection.ontrack = ({ track }) => {
      if (token !== generation || track.kind !== "video") return;
      // The worker returns this frame after face, posture and pulse analysis.
      // Keep the local image until the remote preview is ready.
      update({ stream: new MediaStream([track]) });
    };
    stream.getTracks().forEach((track) => {
      connection.addTrack(track, stream!);
      track.onended = () => {
        if (token === generation)
          stopCamera("Kamera została odłączona. Możesz uruchomić ją ponownie.");
      };
    });
    connection.onconnectionstatechange = () => {
      if (token === generation && connection.connectionState === "failed")
        stopCamera("Połączenie kamery przerwane. Uruchom podgląd ponownie.");
    };
    await connection.setLocalDescription(await connection.createOffer());
    await gather(connection);
    const answer = await api<{
      type: RTCSdpType;
      sdp: string;
      session_id: string;
    }>("/webrtc/offer", "POST", {
      type: "offer",
      sdp: connection.localDescription!.sdp,
    });
    cameraId = answer.session_id;
    if (token !== generation) {
      void api("/sessions/" + cameraId, "DELETE").catch(() => {});
      connection.close();
      return;
    }
    sessionId = cameraId;
    await connection.setRemoteDescription({
      type: answer.type,
      sdp: answer.sdp,
    });
    if (token !== generation) return;
    update({ status: "active" });
    const sample = async () => {
      if (token !== generation || !sessionId) return;
      try {
        const measurement = await api<Measurement>(
          "/sessions/" + sessionId + "/output",
        );
        if (token !== generation) return;
        const stale =
          !Number.isFinite(measurement.timestamp) ||
          Date.now() / 1000 - measurement.timestamp > 5;
        update({ measurement, received: Date.now(), stale });
        if (["closed", "ended", "error"].includes(measurement.status)) {
          stopCamera(
            "Analiza zakończona. Uruchom kamerę ponownie, jeśli chcesz kontynuować.",
          );
          return;
        }
      } catch {
        if (token !== generation) return;
        update({
          stale: true,
          error: "Nie docierają aktualne wyniki analizy.",
        });
      }
      if (token === generation) poll = setTimeout(() => void sample(), 1000);
    };
    void sample();
  } catch (error) {
    stream?.getTracks().forEach((track) => track.stop());
    if (cameraId && cameraId !== sessionId)
      void api("/sessions/" + cameraId, "DELETE").catch(() => {});
    if (token === generation)
      stopCamera(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Brak zgody na kamerę. Zmień uprawnienia w przeglądarce lub kontynuuj bez niej."
          : error instanceof Error
            ? error.message
            : "Nie udało się uruchomić kamery.",
      );
  }
}
window.addEventListener("pagehide", () => stopCamera());
window.addEventListener("bank24:expired", () => stopCamera());
