from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("COLLECTOR_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "participants.sqlite"
SESSIONS_DIR = DATA_DIR / "sessions"

_lock = threading.Lock()
_write_locks: dict[str, threading.Lock] = {}


def _session_lock(session_id: str) -> threading.Lock:
    with _lock:
        if session_id not in _write_locks:
            _write_locks[session_id] = threading.Lock()
        return _write_locks[session_id]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    ensure_dirs()
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL,
            identity_json TEXT NOT NULL,
            victim_code TEXT,
            condition_order TEXT NOT NULL,
            deleted_at REAL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            participant_id INTEGER NOT NULL,
            condition TEXT NOT NULL,
            order_index INTEGER NOT NULL,
            started_at REAL NOT NULL,
            ended_at REAL,
            consents_json TEXT NOT NULL,
            env_json TEXT,
            stats_json TEXT,
            FOREIGN KEY(participant_id) REFERENCES participants(id)
        );
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            command TEXT NOT NULL,
            payload_json TEXT,
            created_at REAL NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            session_id TEXT,
            method TEXT,
            path TEXT,
            status INTEGER,
            duration_ms REAL,
            client_ip TEXT,
            asn TEXT,
            country TEXT,
            user_agent TEXT,
            tls TEXT
        );
        CREATE TABLE IF NOT EXISTS ip_cache (
            ip TEXT PRIMARY KEY,
            asn TEXT,
            country TEXT,
            org TEXT,
            updated_at REAL
        );
        """
    )
    conn.commit()
    conn.close()


def session_dir(session_id: str) -> Path:
    path = SESSIONS_DIR / session_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "video").mkdir(exist_ok=True)
    return path


def append_jsonl(session_id: str, filename: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path = session_dir(session_id) / filename
    lock = _session_lock(session_id)
    with lock:
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(session_id: str, filename: str, payload: Any) -> None:
    path = session_dir(session_id) / filename
    lock = _session_lock(session_id)
    with lock:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_json(session_id: str, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = session_dir(session_id) / filename
    lock = _session_lock(session_id)
    with lock:
        current: dict[str, Any] = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        current.update(payload)
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current


def save_video_chunk(session_id: str, index: int, data: bytes, ext: str = "webm") -> Path:
    path = session_dir(session_id) / "video" / f"{index:04d}.{ext}"
    path.write_bytes(data)
    return path


def count_uploads(session_id: str) -> dict[str, int]:
    d = session_dir(session_id)

    def lines(name: str) -> int:
        p = d / name
        if not p.exists():
            return 0
        with p.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)

    video = list((d / "video").glob("*")) if (d / "video").exists() else []
    return {
        "events": lines("events.jsonl"),
        "face": lines("face.jsonl"),
        "net": lines("net.jsonl"),
        "video_chunks": len(video),
        "video_bytes": sum(p.stat().st_size for p in video),
        "has_survey": int((d / "survey.json").exists()),
        "has_meta": int((d / "meta.json").exists()),
    }


def delete_participant_files(session_ids: list[str]) -> None:
    import shutil

    for sid in session_ids:
        d = SESSIONS_DIR / sid
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def now() -> float:
    return time.time()
