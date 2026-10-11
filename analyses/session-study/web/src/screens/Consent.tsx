import { useProtocol } from "../protocol/ProtocolContext";

export function Consent() {
  const { consents, setConsents, goConsentNext, error, join } = useProtocol();
  const toggle = (k: keyof typeof consents) => setConsents({ ...consents, [k]: !consents[k] });
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Zgoda na udział</h1>
        <p className="lead">
          Uczestnik {join?.code}. Wszystkie dane logowania są fikcyjne i wygenerowane na potrzeby badania. Nie wpisuj
          prawdziwego hasła bankowego.
        </p>
        <p>
          Zapisujemy ruchy myszy, czasy naciśnięć klawiszy (w tym kod klawisza, bo hasła są sztuczne), dane przeglądarki
          i sieci, a opcjonalnie obraz z kamery oraz punkty twarzy i postawy. Dane są przypisane do pseudonimu, leżą na
          naszym serwerze i możesz poprosić o ich usunięcie.
        </p>
        <label className="check">
          <input type="checkbox" checked={consents.study} onChange={() => toggle("study")} />
          <span>Chcę wziąć udział w badaniu i rozumiem, że to nie jest prawdziwy bank.</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.keyboard_mouse} onChange={() => toggle("keyboard_mouse")} />
          <span>Zgoda na zapis klawiatury, myszy i zdarzeń w formularzu (wymagane).</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.face_pose} onChange={() => toggle("face_pose")} />
          <span>Zgoda na punkty twarzy, postawę i średni kolor skóry z kamery (bez wysyłania twarzy, jeśli nie wyrazisz zgody na wideo).</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.video} onChange={() => toggle("video")} />
          <span>Zgoda na nagranie wideo z kamery (osobna, opcjonalna). Wideo kasujemy po wyliczeniu tętna.</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.motion} onChange={() => toggle("motion")} />
          <span>Zgoda na czujniki ruchu telefonu (opcjonalne, tylko na telefonie).</span>
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn" onClick={goConsentNext}>
          Akceptuję i zaczynam
        </button>
      </div>
    </div>
  );
}
