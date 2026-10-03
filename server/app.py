from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import identities
import ipinfo
import storage

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "hackyeah")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

CONDITIONS = ["calibration", "enroll", "calm_1", "calm_2", "dictation", "scam", "intruder", "calm_3"]


def default_order() -> list[str]:
    middle = ["dictation", "scam", "intruder"]
    shuffled = middle[:]
    # deterministic shuffle later per participant
    return ["calm_1", "calm_2", *shuffled, "calm_3"]


def refresh_unused_identities() -> None:
    """Older identities had long numeric IDs and complex passwords; regenerate those not used yet."""
    conn = storage.connect()
    people = conn.execute("SELECT id, code, identity_json FROM participants WHERE deleted_at IS NULL").fetchall()
    for p in people:
        ident = json.loads(p["identity_json"])
        if ident.get("v") == identities.IDENTITY_VERSION:
            continue
        used = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE participant_id=? AND ended_at IS NOT NULL AND condition != 'calibration'",
            (p["id"],),
        ).fetchone()["c"]
        if used:
            continue
        seed = "VICTIM-SEED" if p["code"] == "P-VICTIM" else p["code"]
        conn.execute(
            "UPDATE participants SET identity_json=? WHERE id=?",
            (json.dumps(identities.make_identity(seed), ensure_ascii=False), p["id"]),
        )
    conn.commit()
    conn.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    refresh_unused_identities()
    yield


app = FastAPI(title="Bank24 collector", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConsentIn(BaseModel):
    study: bool
    keyboard_mouse: bool
    face_pose: bool
    video: bool
    motion: bool


class CreateSessionIn(BaseModel):
    participant_code: str
    condition: str
    order_index: int
    consents: ConsentIn


class EventsIn(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class FaceIn(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class NetIn(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)


class SurveyIn(BaseModel):
    stress: int
    hurry: int
    note: str | None = None


class MetaIn(BaseModel):
    payload: dict[str, Any]


class ParticipantIn(BaseModel):
    note: str | None = None


class CommandIn(BaseModel):
    command: str
    payload: dict[str, Any] | None = None


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
    key: str | None = Query(default=None),
):
    token = key
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if x_admin_key:
        token = x_admin_key
    if token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    session_id = request.headers.get("x-session-id")
    response = await call_next(request)
    duration = (time.perf_counter() - t0) * 1000
    ip = ipinfo.client_ip({k.lower(): v for k, v in request.headers.items()}, request.client.host if request.client else None)
    geo = ipinfo.lookup_ip(ip)
    tls = request.headers.get("cf-tls-version") or request.headers.get("x-tls-version")
    try:
        conn = storage.connect()
        conn.execute(
            """INSERT INTO request_log(ts, session_id, method, path, status, duration_ms, client_ip, asn, country, user_agent, tls)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                time.time(),
                session_id,
                request.method,
                str(request.url.path),
                response.status_code,
                round(duration, 3),
                ip,
                geo.get("asn"),
                geo.get("country"),
                request.headers.get("user-agent"),
                tls,
            ),
        )
        conn.commit()
        conn.close()
        if session_id:
            storage.append_jsonl(
                session_id,
                "net.jsonl",
                [
                    {
                        "type": "server_request",
                        "t_epoch": time.time() * 1000,
                        "method": request.method,
                        "path": str(request.url.path),
                        "status": response.status_code,
                        "duration_ms": round(duration, 3),
                        "ip": ip,
                        "asn": geo.get("asn"),
                        "country": geo.get("country"),
                        "tls": tls,
                    }
                ],
            )
    except Exception:
        pass
    response.headers["X-Server-Time"] = str(time.time())
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


@app.get("/api/clock")
def clock():
    return {"server_epoch_ms": time.time() * 1000, "server_perf_ns": time.perf_counter_ns()}


@app.post("/api/ping")
async def ping(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    return {
        "server_epoch_ms": time.time() * 1000,
        "echo": body,
    }


@app.post("/api/admin/login")
def admin_login(payload: dict[str, str]):
    if payload.get("password") != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="bad password")
    return {"token": ADMIN_PASSWORD}


@app.post("/api/admin/participants")
def create_participant(_admin: bool = Depends(require_admin), body: ParticipantIn | None = None):
    conn = storage.connect()
    n = conn.execute("SELECT COUNT(*) AS c FROM participants").fetchone()["c"] + 1
    code = identities.participant_code(n)
    identity = identities.make_identity(code)
    others = conn.execute(
        "SELECT code, identity_json FROM participants WHERE deleted_at IS NULL AND code != ? ORDER BY id DESC",
        (code,),
    ).fetchall()
    victim_code = others[0]["code"] if others else None
    if not victim_code:
        dummy = identities.make_identity("VICTIM-SEED")
        dummy_code = "P-VICTIM"
        existing = conn.execute("SELECT id FROM participants WHERE code=?", (dummy_code,)).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO participants(code, created_at, identity_json, victim_code, condition_order)
                   VALUES (?,?,?,?,?)""",
                (
                    dummy_code,
                    storage.now(),
                    json.dumps(dummy, ensure_ascii=False),
                    None,
                    json.dumps(default_order()),
                ),
            )
        victim_code = dummy_code
    import random

    rng = random.Random(code)
    middle = ["dictation", "scam", "intruder"]
    rng.shuffle(middle)
    order = ["calm_1", "calm_2", *middle, "calm_3"]
    conn.execute(
        """INSERT INTO participants(code, created_at, identity_json, victim_code, condition_order)
           VALUES (?,?,?,?,?)""",
        (code, storage.now(), json.dumps(identity, ensure_ascii=False), victim_code, json.dumps(order)),
    )
    conn.commit()
    conn.close()
    return {"code": code, "identity": identity, "victim_code": victim_code, "condition_order": order}


@app.get("/api/admin/participants")
def list_participants(_admin: bool = Depends(require_admin)):
    conn = storage.connect()
    people = conn.execute(
        "SELECT * FROM participants WHERE deleted_at IS NULL ORDER BY id DESC"
    ).fetchall()
    out = []
    for p in people:
        sessions = conn.execute(
            "SELECT id, condition, order_index, started_at, ended_at, stats_json FROM sessions WHERE participant_id=? ORDER BY order_index",
            (p["id"],),
        ).fetchall()
        sess = []
        for s in sessions:
            stats = json.loads(s["stats_json"]) if s["stats_json"] else {}
            uploads = storage.count_uploads(s["id"])
            sess.append({**_row_to_dict(s), "stats": stats, "uploads": uploads})
        ident = json.loads(p["identity_json"])
        out.append(
            {
                "id": p["id"],
                "code": p["code"],
                "created_at": p["created_at"],
                "full_name": ident.get("full_name"),
                "client_id": ident.get("client_id"),
                "victim_code": p["victim_code"],
                "condition_order": json.loads(p["condition_order"]),
                "sessions": sess,
            }
        )
    conn.close()
    return {"participants": out}


@app.get("/api/admin/leaderboard")
def leaderboard(_admin: bool = Depends(require_admin)):
    conn = storage.connect()
    rows = conn.execute(
        """SELECT s.id, s.stats_json, s.started_at, s.ended_at, p.code, p.identity_json
           FROM sessions s JOIN participants p ON p.id = s.participant_id
           WHERE s.condition='intruder' AND p.deleted_at IS NULL"""
    ).fetchall()
    conn.close()
    board = []
    for r in rows:
        stats = json.loads(r["stats_json"] or "{}")
        ident = json.loads(r["identity_json"])
        board.append(
            {
                "code": r["code"],
                "name": ident.get("full_name"),
                "amount": stats.get("transferred", 0),
                "seconds": stats.get("duration_s"),
                "success": stats.get("success", False),
            }
        )
    board.sort(key=lambda x: (x["success"], x["amount"] or 0), reverse=True)
    return {"board": board}


@app.delete("/api/admin/participants/{code}")
def delete_participant(code: str, _admin: bool = Depends(require_admin)):
    conn = storage.connect()
    p = conn.execute("SELECT id FROM participants WHERE code=?", (code,)).fetchone()
    if not p:
        raise HTTPException(404, "not found")
    sessions = conn.execute("SELECT id FROM sessions WHERE participant_id=?", (p["id"],)).fetchall()
    sids = [s["id"] for s in sessions]
    conn.execute("UPDATE participants SET deleted_at=? WHERE id=?", (storage.now(), p["id"]))
    conn.commit()
    conn.close()
    storage.delete_participant_files(sids)
    return {"ok": True, "removed_sessions": sids}


@app.post("/api/admin/sessions/{session_id}/command")
def push_command(session_id: str, body: CommandIn, _admin: bool = Depends(require_admin)):
    conn = storage.connect()
    conn.execute(
        "INSERT INTO commands(session_id, command, payload_json, created_at) VALUES (?,?,?,?)",
        (session_id, body.command, json.dumps(body.payload or {}), storage.now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/sessions/{session_id}/commands")
def pull_commands(session_id: str):
    conn = storage.connect()
    rows = conn.execute(
        "SELECT id, command, payload_json, created_at FROM commands WHERE session_id=? AND consumed=0 ORDER BY id",
        (session_id,),
    ).fetchall()
    ids = [r["id"] for r in rows]
    if ids:
        conn.executemany("UPDATE commands SET consumed=1 WHERE id=?", [(i,) for i in ids])
        conn.commit()
    conn.close()
    return {
        "commands": [
            {"id": r["id"], "command": r["command"], "payload": json.loads(r["payload_json"] or "{}")}
            for r in rows
        ]
    }


@app.get("/api/join/{code}")
def join(code: str):
    conn = storage.connect()
    p = conn.execute(
        "SELECT * FROM participants WHERE code=? AND deleted_at IS NULL", (code.upper(),)
    ).fetchone()
    if not p:
        raise HTTPException(404, "Nie znaleziono kodu uczestnika")
    victim = None
    if p["victim_code"]:
        v = conn.execute("SELECT code, identity_json FROM participants WHERE code=?", (p["victim_code"],)).fetchone()
        if v:
            victim = {"code": v["code"], "identity": json.loads(v["identity_json"])}
    sessions = conn.execute(
        "SELECT id, condition, order_index, started_at, ended_at FROM sessions WHERE participant_id=? ORDER BY order_index",
        (p["id"],),
    ).fetchall()
    conn.close()
    return {
        "code": p["code"],
        "identity": json.loads(p["identity_json"]),
        "victim": victim,
        "condition_order": json.loads(p["condition_order"]),
        "sessions": [_row_to_dict(s) for s in sessions],
    }


@app.post("/api/sessions")
def create_session(body: CreateSessionIn):
    if body.condition not in CONDITIONS and not body.condition.startswith("calm"):
        raise HTTPException(400, f"unknown condition: {body.condition}")
    conn = storage.connect()
    p = conn.execute(
        "SELECT * FROM participants WHERE code=? AND deleted_at IS NULL", (body.participant_code.upper(),)
    ).fetchone()
    if not p:
        raise HTTPException(404, "participant not found")
    sid = str(uuid.uuid4())
    consents = body.consents.model_dump()
    conn.execute(
        """INSERT INTO sessions(id, participant_id, condition, order_index, started_at, consents_json)
           VALUES (?,?,?,?,?,?)""",
        (sid, p["id"], body.condition, body.order_index, storage.now(), json.dumps(consents)),
    )
    conn.commit()
    victim = None
    if p["victim_code"]:
        v = conn.execute("SELECT code, identity_json FROM participants WHERE code=?", (p["victim_code"],)).fetchone()
        if v:
            victim = {"code": v["code"], "identity": json.loads(v["identity_json"])}
    conn.close()
    storage.write_json(
        sid,
        "meta.json",
        {
            "session_id": sid,
            "participant_code": p["code"],
            "condition": body.condition,
            "order_index": body.order_index,
            "started_at": storage.now(),
            "consents": consents,
            "condition_order": json.loads(p["condition_order"]),
            "victim_code": p["victim_code"],
            "acting_identity": (victim or {}).get("identity") if body.condition == "intruder" else json.loads(p["identity_json"]),
        },
    )
    return {
        "session_id": sid,
        "identity": json.loads(p["identity_json"]),
        "victim": victim,
        "condition": body.condition,
    }


@app.post("/api/sessions/{session_id}/events")
def ingest_events(session_id: str, body: EventsIn):
    storage.append_jsonl(session_id, "events.jsonl", body.rows)
    return {"ok": True, "n": len(body.rows)}


@app.post("/api/sessions/{session_id}/face")
def ingest_face(session_id: str, body: FaceIn):
    storage.append_jsonl(session_id, "face.jsonl", body.rows)
    return {"ok": True, "n": len(body.rows)}


@app.post("/api/sessions/{session_id}/net")
def ingest_net(session_id: str, body: NetIn):
    storage.append_jsonl(session_id, "net.jsonl", body.rows)
    return {"ok": True, "n": len(body.rows)}


@app.post("/api/sessions/{session_id}/survey")
def ingest_survey(session_id: str, body: SurveyIn):
    storage.write_json(session_id, "survey.json", body.model_dump())
    return {"ok": True}


@app.post("/api/sessions/{session_id}/meta")
def ingest_meta(session_id: str, body: MetaIn):
    storage.merge_json(session_id, "meta.json", body.payload)
    return {"ok": True}


@app.post("/api/sessions/{session_id}/complete")
async def complete_session(session_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    conn = storage.connect()
    conn.execute(
        "UPDATE sessions SET ended_at=?, stats_json=? WHERE id=?",
        (storage.now(), json.dumps(payload), session_id),
    )
    conn.commit()
    conn.close()
    storage.merge_json(session_id, "meta.json", {"ended_at": storage.now(), "stats": payload})
    return {"ok": True}


@app.post("/api/sessions/{session_id}/video")
async def ingest_video(
    session_id: str,
    chunk: UploadFile = File(...),
    index: int = Query(0),
):
    data = await chunk.read()
    name = chunk.filename or "chunk.webm"
    ext = name.rsplit(".", 1)[-1] if "." in name else "webm"
    path = storage.save_video_chunk(session_id, index, data, ext=ext)
    storage.append_jsonl(
        session_id,
        "net.jsonl",
        [
            {
                "type": "video_chunk",
                "t_epoch": time.time() * 1000,
                "index": index,
                "bytes": len(data),
                "path": str(path.name),
                "content_type": chunk.content_type,
            }
        ],
    )
    return {"ok": True, "bytes": len(data)}


@app.get("/api/admin/sessions/{session_id}/video")
def session_video(session_id: str, _admin: bool = Depends(require_admin)):
    """MediaRecorder timeslice chunks only form a playable file when concatenated in order."""
    video_dir = storage.SESSIONS_DIR / session_id / "video"
    chunks = sorted(video_dir.glob("*.webm")) if video_dir.exists() else []
    if not chunks:
        raise HTTPException(404, "brak nagrania dla tej sesji")

    def stream():
        for path in chunks:
            with path.open("rb") as fh:
                while block := fh.read(1 << 20):
                    yield block

    return StreamingResponse(
        stream(),
        media_type="video/webm",
        headers={"Content-Disposition": f'inline; filename="{session_id}.webm"'},
    )


@app.get("/api/admin/sessions/{session_id}/uploads")
def uploads(session_id: str, _admin: bool = Depends(require_admin)):
    return storage.count_uploads(session_id)


@app.get("/api/admin/live")
def live(_admin: bool = Depends(require_admin)):
    conn = storage.connect()
    rows = conn.execute(
        """SELECT s.id, s.condition, s.started_at, s.ended_at, p.code
           FROM sessions s JOIN participants p ON p.id=s.participant_id
           WHERE s.ended_at IS NULL AND p.deleted_at IS NULL
           ORDER BY s.started_at DESC"""
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({**_row_to_dict(r), "uploads": storage.count_uploads(r["id"])})
    return {"live": out}


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        index = WEB_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"error": "frontend not built"}, status_code=404)
