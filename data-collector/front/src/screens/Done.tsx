import { useProtocol } from "../protocol/ProtocolContext";

export function Done() {
  const { join } = useProtocol();
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Dziękujemy</h1>
        <p className="lead">
          To koniec badania{join ? ` dla ${join.code}` : ""}. Możesz zamknąć kartę. Jeśli chcesz usunąć swoje dane,
          powiedz prowadzącemu swój kod.
        </p>
      </div>
    </div>
  );
}
