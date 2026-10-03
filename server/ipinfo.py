from __future__ import annotations

import time
from typing import Any

import httpx

from storage import connect

_CACHE_TTL = 86400 * 7


def lookup_ip(ip: str) -> dict[str, Any]:
    if not ip or ip.startswith("127.") or ip.startswith("::1") or ip.startswith("10.") or ip.startswith("192.168."):
        return {"ip": ip, "asn": None, "country": "local", "org": None}
    conn = connect()
    row = conn.execute("SELECT asn, country, org, updated_at FROM ip_cache WHERE ip=?", (ip,)).fetchone()
    if row and (time.time() - row["updated_at"]) < _CACHE_TTL:
        conn.close()
        return {"ip": ip, "asn": row["asn"], "country": row["country"], "org": row["org"]}
    result = {"ip": ip, "asn": None, "country": None, "org": None}
    try:
        with httpx.Client(timeout=2.5) as client:
            r = client.get(f"http://ip-api.com/json/{ip}", params={"fields": "status,country,as,org,query"})
            data = r.json()
            if data.get("status") == "success":
                result = {
                    "ip": ip,
                    "asn": data.get("as"),
                    "country": data.get("country"),
                    "org": data.get("org"),
                }
    except Exception:
        pass
    conn.execute(
        "INSERT OR REPLACE INTO ip_cache(ip, asn, country, org, updated_at) VALUES (?,?,?,?,?)",
        (ip, result.get("asn"), result.get("country"), result.get("org"), time.time()),
    )
    conn.commit()
    conn.close()
    return result


def client_ip(headers: dict[str, str], peer: str | None) -> str:
    forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = headers.get("x-real-ip") or headers.get("cf-connecting-ip")
    if real:
        return real.strip()
    if peer:
        return peer.split(":")[0]
    return ""
