import { useProtocol } from "../protocol/ProtocolContext";

export function Done() {
  const { join } = useProtocol();
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Thank you</h1>
        <p className="lead">
          The study is complete{join ? ` for ${join.code}` : ""}. You can close this tab. To delete your data, give your code to the facilitator.
        </p>
      </div>
    </div>
  );
}
