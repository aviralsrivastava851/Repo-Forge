"""Supabase Cloud persistence. No SQLite, memory, or mock fallback exists."""
from __future__ import annotations
import os
import time
import uuid
from typing import Any, Optional
from app.services.toon import dumps, loads

_client: Any | None = None

def _configured(value: Optional[str]) -> bool:
    return bool(value and value.strip() and "your_" not in value and "xxx" not in value)

def _credentials() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if not (_configured(url) and _configured(key)):
        raise RuntimeError("Supabase Cloud is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env.local; local persistence is disabled.")
    return url, key

def _get_client() -> Any:
    global _client
    if _client is None:
        from supabase import create_client
        _client = create_client(*_credentials())
    return _client

def _prepare(data: dict) -> dict:
    row = dict(data)
    row.setdefault("id", f"row_{uuid.uuid4().hex[:12]}")
    row.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if "commit" in row and "commit_sha" not in row:
        row["commit_sha"] = row.pop("commit")
    for field in ("events", "input", "assertion", "evidence", "summary", "params", "fixtures"):
        if field in row and isinstance(row[field], (dict, list)):
            # TOON requires a named root for reliable list round-tripping.
            value = {"items": row[field]} if isinstance(row[field], list) else row[field]
            row[f"{field}_toon"] = row.get(f"{field}_toon") or dumps(value)
            row.pop(field, None)
    return row

def _restore(row: Optional[dict]) -> Optional[dict]:
    if row is None: return None
    data = dict(row)
    for field in ("events", "input", "assertion", "evidence", "summary", "params", "fixtures"):
        toon = data.get(f"{field}_toon")
        if isinstance(toon, str) and toon.strip():
            try:
                restored = loads(toon)
                data[field] = restored.get("items", restored) if isinstance(restored, dict) else restored
            except Exception: pass
    if "commit_sha" in data: data["commit"] = data["commit_sha"]
    for field in ("passed", "human_verified"):
        if data.get(field) is not None: data[field] = bool(data[field])
    return data

def insert(table: str, data: dict) -> dict:
    row = _prepare(data)
    _get_client().table(table).insert(row).execute()
    return _restore(row) or row

def upsert(table: str, data: dict, on_conflict: str = "id") -> dict:
    row = _prepare(data)
    _get_client().table(table).upsert(row, on_conflict=on_conflict).execute()
    return _restore(row) or row

def get(table: str, id: str) -> Optional[dict]:
    result = _get_client().table(table).select("*").eq("id", id).limit(1).execute()
    return _restore(result.data[0]) if result.data else None

def list_by(table: str, filters: Optional[dict] = None) -> list[dict]:
    query = _get_client().table(table).select("*")
    for key, value in (filters or {}).items(): query = query.eq(key, value)
    return [_restore(row) for row in (query.execute().data or [])]

def list_all(table: str) -> list[dict]: return list_by(table)

def update(table: str, id: str, data: dict) -> Optional[dict]:
    row = _prepare(data); row.pop("id", None); row.pop("created_at", None)
    _get_client().table(table).update(row).eq("id", id).execute()
    return get(table, id)

def delete(table: str, id: str) -> bool:
    return bool(_get_client().table(table).delete().eq("id", id).execute().data)

def delete_by(table: str, filters: dict) -> int:
    query = _get_client().table(table).delete()
    for key, value in filters.items(): query = query.eq(key, value)
    return len(query.execute().data or [])

def clear_all_investigations() -> dict:
    """Delete only ReproForge investigation data, in FK-safe order."""
    client = _get_client()
    deleted: dict[str, int] = {}
    for table in ("workflow_artifacts", "reports", "runs", "configs", "test_cases", "trajectories", "investigations", "repository_tasks"):
        result = client.table(table).delete().neq("id", "").execute()
        deleted[table] = len(result.data or [])
    return deleted

def health() -> dict:
    try:
        _get_client().table("investigations").select("id", count="exact").limit(1).execute()
        return {"mode": "supabase_cloud", "connected": True, "backend": "Supabase Cloud"}
    except Exception as exc:
        return {"mode": "supabase_cloud", "connected": False, "backend": "Supabase Cloud", "error": str(exc)[:240]}
