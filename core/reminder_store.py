"""
core/reminder_store.py: a list of the reminders that were set.

The reminder action hands each reminder to the operating system's scheduler
(launchd on macOS, Task Scheduler on Windows, systemd or `at` on Linux) and then
forgets it, so there was no way to ask "what reminders do I have?" or to cancel
one. This file is the missing memory: one small JSON index next to the scripts
the reminders run. It holds no scheduling logic; the OS still does the waking.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()
_FMT = "%Y-%m-%dT%H:%M:%S"


def store_dir() -> Path:
    override = os.environ.get("JARVIS_REMINDER_DIR")
    d = Path(override) if override else Path.home() / ".jarvis" / "reminders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index() -> Path:
    return store_dir() / "index.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_index().read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and e.get("id")] if isinstance(data, list) else []
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    tmp = _index().with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_index())


def add(task_id: str, when: datetime, message: str, os_name: str, job: str) -> None:
    with _lock:
        entries = [e for e in _load() if e["id"] != task_id]
        entries.append({"id": task_id, "when": when.strftime(_FMT), "message": message,
                        "os": os_name, "job": job})
        _save(entries)


def list_pending(now: datetime | None = None, prune: bool = True) -> list[dict]:
    """Reminders still to come, soonest first. Ones already past are dropped."""
    now = now or datetime.now()
    with _lock:
        entries = _load()
        future = []
        for e in entries:
            try:
                if datetime.strptime(e["when"], _FMT) > now:
                    future.append(e)
            except Exception:
                continue
        if prune and len(future) != len(entries):
            _save(future)
        return sorted(future, key=lambda e: e["when"])


def remove(task_id: str) -> None:
    with _lock:
        _save([e for e in _load() if e["id"] != task_id])


def find(query: str, now: datetime | None = None) -> list[dict]:
    """Pending reminders whose message contains `query` (case-insensitive).
    'all' or an empty query matches everything."""
    pending = list_pending(now)
    q = (query or "").strip().lower()
    if q in ("", "all", "everything"):
        return pending
    return [e for e in pending if q in str(e.get("message", "")).lower()
            or q in str(e.get("when", "")).lower()]


def describe(entry: dict) -> str:
    try:
        when = datetime.strptime(entry["when"], _FMT).strftime("%b %d at %I:%M %p").replace(" 0", " ")
    except Exception:
        when = entry.get("when", "?")
    return f"{when}: {entry.get('message', '')}"
