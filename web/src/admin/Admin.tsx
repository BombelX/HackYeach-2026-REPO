import { useEffect, useMemo, useState } from "react";
import { adminHeaders, api } from "../api";

type Participant = {
  id: number;
  code: string;
  created_at: number;
  full_name: string;
  client_id: string;
  victim_code: string | null;
  condition_order: string[];
  sessions: Array<{
    id: string;
    condition: string;
    started_at: number;
    ended_at: number | null;
    uploads: Record<string, number>;
    stats: Record<string, unknown>;
  }>;
};

export function Admin() {
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(sessionStorage.getItem("admin_token") || "");
  const [error, setError] = useState<string | null>(null);
  const [people, setPeople] = useState<Participant[]>([]);
  const [live, setLive] = useState<Array<Record<string, unknown>>>([]);
  const [board, setBoard] = useState<Array<{ code: string; name: string; amount: number; seconds: number; success: boolean }>>([]);
  const [created, setCreated] = useState<Record<string, unknown> | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  const auth = useMemo(() => (token ? adminHeaders(token) : null), [token]);

  const refresh = async (t = token) => {
    const h = adminHeaders(t);
    const [p, l, b] = await Promise.all([
      fetch("/api/admin/participants", { headers: h }).then((r) => r.json()),
      fetch("/api/admin/live", { headers: h }).then((r) => r.json()),
      fetch("/api/admin/leaderboard", { headers: h }).then((r) => r.json()),
    ]);
    setPeople(p.participants || []);
    setLive(l.live || []);
    setBoard(b.board || []);
  };

  useEffect(() => {
    if (!token) return;
    void refresh(token).catch((e) => setError(String(e)));
    const id = window.setInterval(() => void refresh(token).catch(() => undefined), 4000);
    return () => window.clearInterval(id);
  }, [token]);

  if (!token) {
    return (
      <div className="study-shell">
        <div className="study-card">
          <h1>Panel prowadzącego</h1>
          <div className="field">
            <label>Hasło</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} data-field="admin_pw" />
          </div>
          {error && <p className="error">{error}</p>}
          <button
            className="btn"
            onClick={async () => {
              try {
                const res = await api.adminLogin(password);
                sessionStorage.setItem("admin_token", res.token);
                setToken(res.token);
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
              }
            }}
          >
            Wejdź
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h1>Bank24 — prowadzący</h1>
        <button
          className="btn secondary"
          onClick={() => {
            sessionStorage.removeItem("admin_token");
            setToken("");
          }}
        >
          Wyloguj
        </button>
      </div>
      <div className="row" style={{ marginBottom: 16 }}>
        <button
          className="btn accent"
          onClick={async () => {
            const res = await fetch("/api/admin/participants", {
              method: "POST",
              headers: auth!,
              body: "{}",
            }).then((r) => r.json());
            setCreated(res);
            await refresh();
          }}
        >
          Nowy uczestnik
        </button>
        <button className="btn secondary" onClick={() => void refresh()}>
          Odśwież
        </button>
      </div>
      {created && (
        <div className="card" style={{ marginBottom: 16 }}>
          <strong>Kod: {(created as { code: string }).code}</strong>
          <pre className="invoice">{JSON.stringify((created as { identity: unknown }).identity, null, 2)}</pre>
        </div>
      )}
      <h3>Na żywo</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Kod</th>
            <th>Sesja</th>
            <th>Warunek</th>
            <th>Zdarzenia</th>
            <th>Twarz</th>
            <th>Wideo</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {live.map((row) => (
            <tr key={String(row.id)}>
              <td>{String(row.code)}</td>
              <td className="tiny">{String(row.id).slice(0, 8)}</td>
              <td>
                <span className="pill">{String(row.condition)}</span>
              </td>
              <td>{(row.uploads as { events?: number })?.events ?? 0}</td>
              <td>{(row.uploads as { face?: number })?.face ?? 0}</td>
              <td>{(row.uploads as { video_chunks?: number })?.video_chunks ?? 0}</td>
              <td>
                <button
                  className="btn secondary"
                  onClick={() =>
                    void fetch(`/api/admin/sessions/${row.id}/command`, {
                      method: "POST",
                      headers: auth!,
                      body: JSON.stringify({ command: "start_call", payload: {} }),
                    })
                  }
                >
                  Telefon
                </button>
              </td>
            </tr>
          ))}
          {!live.length && (
            <tr>
              <td colSpan={7} className="muted">
                Brak otwartych sesji
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <h3>Włamywacze</h3>
      <table className="table">
        <thead>
          <tr>
            <th>#</th>
            <th>Kod</th>
            <th>Kwota</th>
            <th>Czas</th>
            <th>Sukces</th>
          </tr>
        </thead>
        <tbody>
          {board.map((b, i) => (
            <tr key={b.code + i}>
              <td>{i + 1}</td>
              <td>{b.code}</td>
              <td>{b.amount}</td>
              <td>{b.seconds ? Number(b.seconds).toFixed(1) + " s" : "—"}</td>
              <td>{b.success ? "tak" : "nie"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Uczestnicy</h3>
      <table className="table">
        <thead>
          <tr>
            <th>Kod</th>
            <th>Imię</th>
            <th>Ofiara</th>
            <th>Sesje</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {people.filter((p) => p.code !== "P-VICTIM").map((p) => (
            <tr key={p.code}>
              <td>
                <strong>{p.code}</strong>
                <div className="tiny">{p.client_id}</div>
              </td>
              <td>{p.full_name}</td>
              <td>{p.victim_code}</td>
              <td>
                {p.sessions.map((s) => (
                  <div key={s.id} className="tiny">
                    {s.condition} {s.ended_at ? "✓" : "…"} ev:{s.uploads.events} cam:{s.uploads.video_chunks}{" "}
                    {s.uploads.video_chunks > 0 && (
                      <button className="btn ghost" style={{ padding: "2px 6px" }} onClick={() => setPlaying(s.id)}>
                        ▶ wideo
                      </button>
                    )}
                  </div>
                ))}
              </td>
              <td>
                <button
                  className="btn danger"
                  onClick={async () => {
                    if (!confirm(`Usunąć dane ${p.code}?`)) return;
                    await fetch(`/api/admin/participants/${p.code}`, { method: "DELETE", headers: auth! });
                    await refresh();
                  }}
                >
                  Usuń
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="error">{error}</p>}

      {playing && (
        <div className="overlay" onClick={() => setPlaying(null)}>
          <div className="modal" style={{ width: "min(760px, 94vw)" }} onClick={(e) => e.stopPropagation()}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong className="tiny">{playing}</strong>
              <div className="row">
                <a
                  className="btn secondary"
                  href={`/api/admin/sessions/${playing}/video?key=${encodeURIComponent(token)}`}
                  download={`${playing}.webm`}
                >
                  Pobierz
                </a>
                <button className="btn secondary" onClick={() => setPlaying(null)}>
                  Zamknij
                </button>
              </div>
            </div>
            <video
              key={playing}
              src={`/api/admin/sessions/${playing}/video?key=${encodeURIComponent(token)}`}
              controls
              autoPlay
              style={{ width: "100%", marginTop: 12, background: "#000", borderRadius: 8 }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
