import { useState } from "react";
import { useProtocol } from "../protocol/ProtocolContext";

export function Survey() {
  const { submitSurvey, condition } = useProtocol();
  const [stress, setStress] = useState(4);
  const [hurry, setHurry] = useState(4);
  const [note, setNote] = useState("");
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>After session {condition}</h1>
        <p className="lead">How did you feel? 1 = not at all, 7 = very much.</p>
        <p>How stressed were you?</p>
        <div className="scale">
          {Array.from({ length: 7 }, (_, i) => i + 1).map((n) => (
            <button key={n} className={n === stress ? "on" : ""} onClick={() => setStress(n)}>
              {n}
            </button>
          ))}
        </div>
        <p>How rushed did you feel?</p>
        <div className="scale">
          {Array.from({ length: 7 }, (_, i) => i + 1).map((n) => (
            <button key={n} className={n === hurry ? "on" : ""} onClick={() => setHurry(n)}>
              {n}
            </button>
          ))}
        </div>
        <div className="field">
          <label>Note (optional)</label>
          <textarea data-field="survey_note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
        </div>
        <button className="btn" onClick={() => void submitSurvey(stress, hurry, note || undefined)}>
          Continue
        </button>
      </div>
    </div>
  );
}
