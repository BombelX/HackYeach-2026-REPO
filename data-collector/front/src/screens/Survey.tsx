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
        <h1>Po sesji {condition}</h1>
        <p className="lead">Jak się czułeś? 1 = wcale, 7 = bardzo.</p>
        <p>Jak bardzo byłeś zestresowany?</p>
        <div className="scale">
          {Array.from({ length: 7 }, (_, i) => i + 1).map((n) => (
            <button key={n} className={n === stress ? "on" : ""} onClick={() => setStress(n)}>
              {n}
            </button>
          ))}
        </div>
        <p>Jak bardzo się spieszyłeś?</p>
        <div className="scale">
          {Array.from({ length: 7 }, (_, i) => i + 1).map((n) => (
            <button key={n} className={n === hurry ? "on" : ""} onClick={() => setHurry(n)}>
              {n}
            </button>
          ))}
        </div>
        <div className="field">
          <label>Uwaga (opcjonalnie)</label>
          <textarea data-field="survey_note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
        </div>
        <button className="btn" onClick={() => void submitSurvey(stress, hurry, note || undefined)}>
          Dalej
        </button>
      </div>
    </div>
  );
}
