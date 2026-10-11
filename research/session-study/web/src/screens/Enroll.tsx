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
        <h1>Your Bank24 credentials</h1>
        <p className="lead">
          Remember the ID and password. In calm sessions, sign in to your own account. These are not real bank credentials.
        </p>
        <div className="invoice">
          <div>Owner: {identity.full_name}</div>
          <div>ID: {identity.client_id}</div>
          <div>Password: {identity.password}</div>
          <div>SMS code: {identity.sms_code}</div>
          <div>Your date of birth: {identity.birth_date}</div>
        </div>
        <p className="tiny">Type them now to establish your own typing rhythm.</p>
        <div className="field">
          <label>ID</label>
          <input data-field="enroll_id" value={id} onChange={(e) => setId(e.target.value)} autoComplete="off" />
        </div>
        <div className="field">
          <label>Password</label>
          <input data-field="enroll_pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="off" />
        </div>
        {err && <p className="error">{err}</p>}
        <button
          className="btn"
          onClick={() => {
            if (id !== identity.client_id || pw !== identity.password) {
              setErr("The ID or password does not match the card above.");
              return;
            }
            void finishEnroll();
          }}
        >
          Remembered, continue
        </button>
      </div>
    </div>
  );
}
