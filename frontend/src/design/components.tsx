import {
  useEffect,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { ApiError, errorMessage } from "../services/api";

export function Bank24Logo() {
  return (
    <img src="/brand/bank24-logo.svg" width="252" height="64" alt="Bank24" />
  );
}
export function Icon({
  name,
  size = 20,
}: {
  name: "home" | "transfer" | "history" | "help" | "bell" | "arrow" | "search" | "shield" | "camera" | "copy";
  size?: number;
}) {
  const paths = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z" /><path d="M9 21v-6h6v6" /></>,
    transfer: <><path d="M4 7h13" /><path d="m13 3 4 4-4 4" /><path d="M20 17H7" /><path d="m11 13-4 4 4 4" /></>,
    history: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.8 9a2.4 2.4 0 0 1 4.7.8c0 1.6-2.5 2-2.5 3.7" /><path d="M12 17.5h.01" /></>,
    bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    arrow: <><path d="M4 12h15" /><path d="m13 6 6 6-6 6" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    shield: <><path d="M12 3 20 6v5c0 5-3.4 8.4-8 10-4.6-1.6-8-5-8-10V6Z" /><path d="m8.8 12 2.1 2.1 4.4-4.5" /></>,
    camera: <><rect x="3" y="7" width="15" height="13" rx="2" /><path d="m18 11 3-2v9l-3-2" /><path d="m7 7 1.5-2h4L14 7" /></>,
    copy: <><rect x="8" y="8" width="11" height="12" rx="2" /><path d="M5 16H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>,
  }[name];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths}
    </svg>
  );
}
export function Field({
  label,
  error,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
}) {
  const fallback = useId();
  const id = props.id || fallback;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        {...props}
        id={id}
        aria-invalid={!!error}
        aria-describedby={
          error ? id + "-error" : hint ? id + "-hint" : undefined
        }
      />
      {hint && (
        <p id={id + "-hint"} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={id + "-error"} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
export function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <div role="alert" className="notice error">
      {errorMessage(error)}
      {error instanceof ApiError && error.status === 401 && (
        <p>
          <a href="/login">Przejdź do logowania</a>
        </p>
      )}
    </div>
  ) : null;
}
export function Status({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="status-message">
      {children}
    </p>
  );
}
export function Loading() {
  return (
    <div aria-busy="true" role="status" className="loading">
      <span className="skeleton" />
      <span className="skeleton" />
      Pobieramy dane…
    </div>
  );
}
export function PageTitle({ title, intro }: { title: string; intro?: string }) {
  return (
    <>
      <h1 tabIndex={-1}>{title}</h1>
      {intro && <p className="intro">{intro}</p>}
    </>
  );
}
export function Steps({
  current,
  labels = ["Dane", "Sprawdzenie", "Potwierdzenie"],
  ariaLabel = "Etapy przelewu",
}: {
  current: number;
  labels?: string[];
  ariaLabel?: string;
}) {
  return (
    <ol className="steps" aria-label={ariaLabel}>
      {labels.map((label, i) => (
        <li key={label} aria-current={i === current ? "step" : undefined}>
          <span>{i + 1}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}
export function useErrorFocus(error: unknown) {
  useEffect(() => {
    if (error)
      document
        .querySelector<HTMLInputElement>('[aria-invalid="true"]')
        ?.focus();
  }, [error]);
}
export function CameraIcon() {
  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
    >
      <rect x="3" y="8" width="19" height="17" rx="3" />
      <path d="m22 13 7-4v15l-7-4M10 8l2-3h5l2 3" />
    </svg>
  );
}
