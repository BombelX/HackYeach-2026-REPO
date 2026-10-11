import { useProtocol } from "../protocol/ProtocolContext";

export function Consent() {
  const { consents, setConsents, goConsentNext, error, join } = useProtocol();
  const toggle = (k: keyof typeof consents) => setConsents({ ...consents, [k]: !consents[k] });
  return (
    <div className="study-shell">
      <div className="study-card">
        <h1>Participation consent</h1>
        <p className="lead">
          Participant {join?.code}. All credentials are fictional and generated for this study. Do not enter your real banking password.
        </p>
        <p>
          We record mouse movements, keystroke timing (including key codes because the passwords are artificial), browser and network data, and optionally camera video and face and pose landmarks. Data is linked to a pseudonym and stored on our server. You can request its deletion.
        </p>
        <label className="check">
          <input type="checkbox" checked={consents.study} onChange={() => toggle("study")} />
          <span>I want to participate in the study and understand that this is not a real bank.</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.keyboard_mouse} onChange={() => toggle("keyboard_mouse")} />
          <span>I consent to recording keyboard, mouse and form events (required).</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.face_pose} onChange={() => toggle("face_pose")} />
          <span>I consent to camera face landmarks, posture and average skin color (no face video is sent unless I consent to video).</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.video} onChange={() => toggle("video")} />
          <span>I consent to camera video recording (separate and optional). Video is deleted after pulse extraction.</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={consents.motion} onChange={() => toggle("motion")} />
          <span>I consent to phone motion sensors (optional, phone only).</span>
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn" onClick={goConsentNext}>
          Accept and start
        </button>
      </div>
    </div>
  );
}
