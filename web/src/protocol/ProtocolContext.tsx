import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { SessionRecorder } from "../recorder/SessionRecorder";
import type { Condition, Consents, Identity, JoinResponse, Victim } from "../types";

export type Step = "code" | "consent" | "calibration" | "enroll" | "briefing" | "bank" | "survey" | "done";

type ProtocolState = {
  step: Step;
  code: string;
  join: JoinResponse | null;
  consents: Consents;
  index: number;
  sessionId: string | null;
  recorder: SessionRecorder | null;
  lastStats: Record<string, unknown> | null;
  error: string | null;
  previewRef: React.RefObject<HTMLVideoElement | null>;
};

type Ctx = ProtocolState & {
  condition: Condition | null;
  identity: Identity | null;
  actingIdentity: Identity | null;
  victim: Victim | null;
  setCode: (c: string) => void;
  loadParticipant: () => Promise<void>;
  setConsents: (c: Consents) => void;
  goConsentNext: () => void;
  startCalibration: () => Promise<void>;
  finishCalibration: () => Promise<void>;
  finishEnroll: () => Promise<void>;
  beginCondition: () => Promise<void>;
  finishBank: (stats: Record<string, unknown>) => Promise<void>;
  submitSurvey: (stress: number, hurry: number, note?: string) => Promise<void>;
};

const defaultConsents: Consents = {
  study: false,
  keyboard_mouse: true,
  face_pose: true,
  video: true,
  motion: false,
};

const ProtocolContext = createContext<Ctx | null>(null);

export function ProtocolProvider({ children }: { children: ReactNode }) {
  const previewRef = useRef<HTMLVideoElement | null>(null);
  const [step, setStep] = useState<Step>("code");
  const [code, setCode] = useState("");
  const [join, setJoin] = useState<JoinResponse | null>(null);
  const [consents, setConsents] = useState<Consents>(defaultConsents);
  const [index, setIndex] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [recorder, setRecorder] = useState<SessionRecorder | null>(null);
  const [lastStats, setLastStats] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const condition = join?.condition_order[index] ?? null;
  const identity = join?.identity ?? null;
  const victim = join?.victim ?? null;
  const actingIdentity = condition === "intruder" ? victim?.identity ?? identity : identity;

  const stopRecorder = useCallback(async (rec: SessionRecorder | null) => {
    if (rec) await rec.stop();
  }, []);

  const openSession = useCallback(
    async (cond: string, orderIndex: number) => {
      if (!join) throw new Error("brak uczestnika");
      const created = await api.createSession({
        participant_code: join.code,
        condition: cond,
        order_index: orderIndex,
        consents,
      });
      const rec = new SessionRecorder(created.session_id, consents);
      await rec.start(previewRef.current);
      setSessionId(created.session_id);
      setRecorder(rec);
      return rec;
    },
    [join, consents],
  );

  const loadParticipant = useCallback(async () => {
    setError(null);
    try {
      const data = await api.join(code.trim().toUpperCase());
      setJoin(data);
      const done = new Set(data.sessions.filter((s) => s.ended_at).map((s) => s.condition));
      const next = data.condition_order.findIndex((c) => !done.has(c));
      setIndex(next === -1 ? data.condition_order.length : Math.max(0, next));
      setStep("consent");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [code]);

  const goConsentNext = () => {
    if (!consents.study || !consents.keyboard_mouse) {
      setError("Do udziału potrzebna jest zgoda na badanie oraz zapis klawiatury i myszy.");
      return;
    }
    setError(null);
    setStep("calibration");
  };

  const startCalibration = useCallback(async () => {
    setError(null);
    try {
      const rec = await openSession("calibration", -1);
      rec.stage("calibration", "start");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [openSession]);

  const finishCalibration = useCallback(async () => {
    if (recorder) {
      recorder.stage("calibration", "end");
      await recorder.flush();
      await api.complete(recorder.sessionId, { kind: "calibration" });
      await stopRecorder(recorder);
    }
    setRecorder(null);
    setSessionId(null);
    setStep("enroll");
  }, [recorder, stopRecorder]);

  const finishEnroll = useCallback(async () => {
    setStep("briefing");
  }, []);

  const beginCondition = useCallback(async () => {
    if (!condition) {
      setStep("done");
      return;
    }
    setError(null);
    try {
      const rec = await openSession(condition, index);
      rec.stage("session", "start");
      rec.stage("login", "start");
      setStep("bank");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [condition, index, openSession]);

  const finishBank = useCallback(
    async (stats: Record<string, unknown>) => {
      setLastStats(stats);
      if (recorder) {
        recorder.stage("session", "end");
        await recorder.flush();
        await api.complete(recorder.sessionId, stats);
        await stopRecorder(recorder);
      }
      setRecorder(null);
      setStep("survey");
    },
    [recorder, stopRecorder],
  );

  const submitSurvey = useCallback(
    async (stress: number, hurry: number, note?: string) => {
      if (sessionId) await api.survey(sessionId, { stress, hurry, note });
      setSessionId(null);
      const next = index + 1;
      if (!join || next >= join.condition_order.length) {
        setStep("done");
        return;
      }
      setIndex(next);
      setStep("briefing");
    },
    [sessionId, index, join],
  );

  const value = useMemo<Ctx>(
    () => ({
      step,
      code,
      join,
      consents,
      index,
      sessionId,
      recorder,
      lastStats,
      error,
      previewRef,
      condition,
      identity,
      actingIdentity,
      victim,
      setCode,
      loadParticipant,
      setConsents,
      goConsentNext,
      startCalibration,
      finishCalibration,
      finishEnroll,
      beginCondition,
      finishBank,
      submitSurvey,
    }),
    [
      step,
      code,
      join,
      consents,
      index,
      sessionId,
      recorder,
      lastStats,
      error,
      condition,
      identity,
      actingIdentity,
      victim,
      loadParticipant,
      startCalibration,
      finishCalibration,
      finishEnroll,
      beginCondition,
      finishBank,
      submitSurvey,
    ],
  );

  return <ProtocolContext.Provider value={value}>{children}</ProtocolContext.Provider>;
}

export function useProtocol() {
  const ctx = useContext(ProtocolContext);
  if (!ctx) throw new Error("ProtocolContext missing");
  return ctx;
}
