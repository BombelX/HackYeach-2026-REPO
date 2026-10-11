import { useProtocol } from "../protocol/ProtocolContext";

export function CodeEntry() {
  const { code, setCode, loadParticipant, error } = useProtocol();
  return (
    <div className="study-shell">
      <div className="study-card">
        <p className="disclaimer">This is not a real bank. This page collects research data at HackYeah 2026.</p>
        <h1>Bank24 — behavioral study</h1>
        <p className="lead">Click “Start study”. If you are returning to an interrupted study, enter your participant code.</p>
        <div className="field">
          <label htmlFor="code">Participant code (optional)</label>
          <input
            id="code"
            data-field="participant_code"
            autoComplete="off"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            onKeyDown={(e) => {
              if (e.key === "Enter") void loadParticipant();
            }}
          />
        </div>
        {error && <p className="error">{error}</p>}
        <button className="btn" onClick={() => void loadParticipant()}>
          {code.trim() ? "Continue" : "Start study"}
        </button>
      </div>
    </div>
  );
}
