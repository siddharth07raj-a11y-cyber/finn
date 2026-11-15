"""Tiny SQLite key-value cache with TTL and stale-on-error reads.

Every upstream call goes through `cached()`. If a source is down or rate-limits us,
the last good answer is served and flagged stale, so the app never goes blank.
"""
import json
import sqlite3
import threading
import time

from .config import DATA_DIR

_lock = threading.Lock()
_db = sqlite3.connect(DATA_DIR / "cache.sqlite", check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, t REAL)")
_db.commit()


def get(key, ttl=None):
    """Return (value, age_seconds) or (None, None). ttl=None accepts any age."""
    with _lock:
        row = _db.execute("SELECT v, t FROM kv WHERE k=?", (key,)).fetchone()
    if not row:
        return None, None
    age = time.time() - row[1]
    if ttl is not None and age > ttl:
        return None, None
    return json.loads(row[0]), age


def put(key, value):
    with _lock:
        _db.execute("REPLACE INTO kv (k, v, t) VALUES (?,?,?)", (key, json.dumps(value), time.time()))
        _db.commit()


def cached(key, ttl, fn):
    """Fresh cache -> live fetch -> stale cache. Returns (value, meta)."""
    val, age = get(key, ttl)
    if val is not None:
        return val, {"cached": True, "stale": False, "age": age}
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001 - any upstream failure falls back to stale
        old, age = get(key)
        if old is not None:
            return old, {"cached": True, "stale": True, "age": age, "error": str(e)[:200]}
        raise
    put(key, val)
    return val, {"cached": False, "stale": False, "age": 0}
