import type { Consents, RecEvent } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || JSON.stringify(j);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ ok: boolean }>("/api/health"),
  clock: () => req<{ server_epoch_ms: number }>("/api/clock"),
  ping: (echo: Record<string, unknown>) =>
    req<{ server_epoch_ms: number; echo: unknown }>("/api/ping", {
      method: "POST",
      body: JSON.stringify(echo),
    }),
  join: (code: string) => req<import("./types").JoinResponse>(`/api/join/${encodeURIComponent(code)}`),
  createSession: (body: {
    participant_code: string;
    condition: string;
    order_index: number;
    consents: Consents;
  }) =>
    req<{
      session_id: string;
      identity: import("./types").Identity;
      victim: import("./types").Victim | null;
      condition: string;
    }>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  events: (sessionId: string, rows: RecEvent[]) =>
    req(`/api/sessions/${sessionId}/events`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify({ rows }),
    }),
  face: (sessionId: string, rows: unknown[]) =>
    req(`/api/sessions/${sessionId}/face`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify({ rows }),
    }),
  net: (sessionId: string, rows: unknown[]) =>
    req(`/api/sessions/${sessionId}/net`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify({ rows }),
    }),
  survey: (sessionId: string, body: { stress: number; hurry: number; note?: string }) =>
    req(`/api/sessions/${sessionId}/survey`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify(body),
    }),
  meta: (sessionId: string, payload: Record<string, unknown>) =>
    req(`/api/sessions/${sessionId}/meta`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify({ payload }),
    }),
  complete: (sessionId: string, stats: Record<string, unknown>) =>
    req(`/api/sessions/${sessionId}/complete`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: JSON.stringify(stats),
    }),
  commands: (sessionId: string) =>
    req<{ commands: Array<{ command: string; payload: Record<string, unknown> }> }>(
      `/api/sessions/${sessionId}/commands`,
    ),
  uploadVideo: async (sessionId: string, index: number, blob: Blob) => {
    const fd = new FormData();
    const ext = blob.type.includes("mp4") ? "mp4" : "webm";
    fd.append("chunk", blob, `chunk.${ext}`);
    const res = await fetch(`/api/sessions/${sessionId}/video?index=${index}`, {
      method: "POST",
      headers: { "X-Session-Id": sessionId },
      body: fd,
    });
    if (!res.ok) throw new Error("video upload failed");
    return res.json();
  },
  adminLogin: (password: string) =>
    req<{ token: string }>("/api/admin/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
};

export function adminHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}
