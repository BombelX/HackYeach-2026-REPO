import { useState } from "react";
import { useProtocol } from "../protocol/ProtocolContext";

export function Enroll() {
  const { identity, finishEnroll } = useProtocol();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!identity) return null;
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Twoje dane do Bank24</h1>
        <p className="lead">
          Zapamiętaj identyfikator i hasło. W spokojnych sesjach logujesz się na swoje konto. To nie są dane prawdziwego
          banku.
        </p>
        <div className="invoice">
          <div>Właściciel: {identity.full_name}</div>
          <div>Identyfikator: {identity.client_id}</div>
          <div>Hasło: {identity.password}</div>
          <div>Kod SMS: {identity.sms_code}</div>
          <div>Data urodzenia (Twoja): {identity.birth_date}</div>
        </div>
        <p className="tiny">Wpisz je teraz, żeby nabrać własnego rytmu pisania.</p>
        <div className="field">
          <label>Identyfikator</label>
          <input data-field="enroll_id" value={id} onChange={(e) => setId(e.target.value)} autoComplete="off" />
        </div>
        <div className="field">
          <label>Hasło</label>
          <input data-field="enroll_pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="off" />
        </div>
        {err && <p className="error">{err}</p>}
        <button
          className="btn"
          onClick={() => {
            if (id !== identity.client_id || pw !== identity.password) {
              setErr("Identyfikator lub hasło nie zgadza się z kartą powyżej.");
              return;
            }
            void finishEnroll();
          }}
        >
          Zapamiętane, dalej
        </button>
      </div>
    </div>
  );
}
