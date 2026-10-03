import { ProtocolProvider, useProtocol } from "./protocol/ProtocolContext";
import { Admin } from "./admin/Admin";
import { BankApp } from "./bank/BankApp";
import { Briefing } from "./screens/Briefing";
import { Calibration } from "./screens/Calibration";
import { CodeEntry } from "./screens/CodeEntry";
import { Consent } from "./screens/Consent";
import { Done } from "./screens/Done";
import { Enroll } from "./screens/Enroll";
import { Survey } from "./screens/Survey";

function Study() {
  const { step } = useProtocol();
  switch (step) {
    case "code":
      return <CodeEntry />;
    case "consent":
      return <Consent />;
    case "calibration":
      return <Calibration />;
    case "enroll":
      return <Enroll />;
    case "briefing":
      return <Briefing />;
    case "bank":
      return <BankApp />;
    case "survey":
      return <Survey />;
    case "done":
      return <Done />;
    default:
      return <CodeEntry />;
  }
}

export default function App() {
  const isAdmin = window.location.pathname.startsWith("/admin") || window.location.hash === "#admin";
  if (isAdmin) return <Admin />;
  return (
    <ProtocolProvider>
      <Study />
    </ProtocolProvider>
  );
}
