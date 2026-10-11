import { useProtocol } from "../protocol/ProtocolContext";

export function CodeEntry() {
  const { code, setCode, loadParticipant, error } = useProtocol();
  return (
    <div className="study-shell">
      <div className="study-card">
        <p className="disclaimer">To nie jest prawdziwy bank. Strona zbiera dane do badania na HackYeah 2026.</p>
        <h1>Bank24 — badanie zachowania</h1>
        <p className="lead">Kliknij „Rozpocznij badanie”. Jeśli wracasz do przerwanego badania, wpisz swój kod uczestnika.</p>
        <div className="field">
          <label htmlFor="code">Kod uczestnika (opcjonalnie)</label>
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
          {code.trim() ? "Dalej" : "Rozpocznij badanie"}
        </button>
      </div>
    </div>
  );
}
