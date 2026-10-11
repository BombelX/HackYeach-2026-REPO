import { QueryClient } from "@tanstack/react-query";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, staleTime: 15_000 },
    mutations: { retry: false },
  },
});
/** Set when the server forces a logout; leave-page guards must not hold the user back. */
export const forcedLogout = { active: false };
export const voluntaryLogout = { active: false };

function clearBankQueries() {
  const privateKeys = new Set([
    "account",
    "history",
    "transfer",
    "login-challenge",
    "transfer-challenge",
    "camera-profile",
    "camera-risk",
  ]);
  queryClient.removeQueries({
    predicate: (query) => privateKeys.has(String(query.queryKey[0])),
  });
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  let response: Response;
  const requestStarted = performance.now();
  try {
    response = await fetch(import.meta.env.BASE_URL + "api" + path, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": body instanceof Blob ? "image/jpeg" : "application/json",
        "X-CSRF-Token": csrf,
        ...headers,
      },
      body: body instanceof Blob ? body : body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(20_000),
      keepalive: method === "DELETE",
    });
  } catch {
    throw new ApiError(
      0,
      "network",
      "Could not connect to the server. Check your connection and try again.",
    );
  }
  if (!path.startsWith("/telemetry/")) window.dispatchEvent(new CustomEvent("bank24:request-timing", {
    detail: { duration_ms: performance.now() - requestStarted, status: response.status },
  }));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    // During a forced logout the countdown owns the redirect; don't jump to login early.
    if (response.status === 401 && !forcedLogout.active && !voluntaryLogout.active) {
      clearBankQueries();
      window.dispatchEvent(new Event("bank24:expired"));
    }
    if (data.code === "anomaly_detected") {
      forcedLogout.active = true;
      clearBankQueries();
      window.dispatchEvent(new CustomEvent("bank24:anomaly", { detail: data.message }));
    }
    throw new ApiError(
      response.status,
      data.code || "server",
      data.message ||
        "The server cannot process the request right now. Try again.",
      data.fields,
    );
  }
  return data as T;
}

export interface Session {
  csrf: string;
  session_id: string;
  telemetry: boolean;
  camera: boolean;
  authenticated: boolean;
  demo_mode: boolean;
}
export interface Invoice {
  recipient: string;
  number: string;
  amount_grosz: number;
  title: string;
  reference: string;
}
export interface Account {
  name: string;
  number: string;
  balance_grosz: number;
  currency: string;
  incoming_grosz: number;
  outgoing_grosz: number;
  month: string;
  trusted_device: boolean;
  invoice: Invoice;
}
export interface Transaction {
  id: string;
  recipient: string;
  title: string;
  amount_grosz: number;
  created: string;
  status: string;
}
export interface History {
  items: Transaction[];
  total: number;
  offset: number;
  limit: number;
}
export interface Challenge {
  challenge_id: string;
  expires_at: number;
  resend_at: number;
  demo_mode: boolean;
  code_length: number;
}
export interface Risk {
  account_takeover_risk: number | null;
  coercion_risk: number | null;
  assessment_status?: "ready" | "limited" | "insufficient_data" | "unavailable";
  quality: string;
  action: string;
  reasons: string[];
  missing_reasons?: string[];
  available_signals?: string[];
  recommended_interventions?: string[];
  validated?: boolean;
  model_version?: string;
  camera_model?: {
    review_score: number;
    review_threshold: number;
    review_required: boolean;
    p_not_owner: number;
    p_pressure: number;
    probe_seconds: number;
    profile_enrolled_now: boolean;
    profile_version?: number;
  };
  assessed_at: number;
}
export interface Transfer {
  id: string;
  version: number;
  recipient: string;
  number: string;
  title: string;
  amount_grosz: number;
  status: string;
  risk: Risk;
  created: string;
  confirmed: string | null;
}

export const sessionOptions = {
  queryKey: ["session"],
  queryFn: async () => {
    const session = await api<Session>("/bootstrap", "POST");
    setCsrf(session.csrf);
    const previous = queryClient.getQueryData<Session>(["session"]);
    if (previous && previous.session_id !== session.session_id)
      clearBankQueries();
    if (previous?.authenticated && !session.authenticated && !forcedLogout.active) {
      clearBankQueries();
      window.dispatchEvent(new Event("bank24:expired"));
    }
    return session;
  },
  staleTime: Infinity,
};
export const accountOptions = {
  queryKey: ["account"],
  queryFn: () => api<Account>("/bank/account"),
};
export interface HistoryFilters {
  offset?: number;
  search?: string;
  direction?: "all" | "incoming" | "outgoing";
}
export const historyOptions = (filters: number | HistoryFilters = 0) => {
  const normalized =
    typeof filters === "number" ? { offset: filters } : filters;
  const offset = normalized.offset ?? 0;
  const search = normalized.search?.trim() ?? "";
  const direction = normalized.direction ?? "all";
  const params = new URLSearchParams({ limit: "30", offset: String(offset) });
  if (search) params.set("q", search);
  if (direction !== "all") params.set("direction", direction);
  return {
    queryKey: ["history", offset, search, direction],
    queryFn: () => api<History>("/bank/transactions?" + params.toString()),
  };
};
export const transferOptions = (id: string) => ({
  queryKey: ["transfer", id],
  queryFn: () => api<Transfer>("/bank/transfers/" + id),
});
export interface RiskCheck {
  available_signals?: string[];
  status: "ok" | "insufficient_data";
  limit: number | null;
  account_takeover_risk: number | null;
  reason: string | null;
  retry_after: number | null;
}
export function checkRisk() {
  return api<RiskCheck>("/bank/risk-check", "POST", {});
}
export interface CameraProfileStatus {
  status: "collecting" | "ready";
  samples: number;
  pending: number;
  required: number;
  version: number | null;
  updated_at: number | null;
  recorded_this_session: boolean;
  activates_next_sign_in: boolean;
  model_available: boolean;
  started_at: number | null;
  approval_available: boolean;
  can_enroll: boolean;
}
export function cameraProfileStatus() {
  return api<CameraProfileStatus>("/bank/camera-profile");
}
export function enrollCameraSample() {
  return api<CameraProfileStatus>("/bank/camera-profile/enroll", "POST", {
    confirm_calm: true,
  });
}
export function startCameraEnrollment() {
  return api<CameraProfileStatus>("/bank/camera-profile/enroll/start", "POST", {
    confirm_calm: true,
  });
}
export function deleteCameraProfile() {
  return api<CameraProfileStatus>("/bank/camera-profile", "DELETE");
}
export function refreshSession() {
  return queryClient.fetchQuery({ ...sessionOptions, staleTime: 0 });
}
export async function updatePermissions(changes: {
  telemetry?: boolean;
  camera?: boolean;
}) {
  const updated = await api<Session>("/session/permissions", "POST", changes);
  setCsrf(updated.csrf);
  queryClient.setQueryData(["session"], updated);
  return updated;
}
export function errorMessage(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Could not complete this action. Try again.";
}
