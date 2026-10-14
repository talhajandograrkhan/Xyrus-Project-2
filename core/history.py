"""
core/history.py: every conversation, kept and searchable.

Until now a conversation lived in the log panel and in a short summary written at
the end of a session, so "what did I ask you yesterday about the invoice?" had no
answer. This file keeps each spoken or typed exchange as one JSON line and offers
a small search over it. It is local only, plain text, and capped in size.
"""
from __future__ import annotations

from core.diag import swallowed as _swallowed
import json
import os
import re
import threading
import time
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024        # then the file rolls over to history.jsonl.1
_lock = threading.Lock()


def history_path() -> Path:
    override = os.environ.get("JARVIS_HISTORY_FILE")
    if override:
        return Path(override)
    try:
        from memory.config_manager import BASE_DIR
        base = Path(BASE_DIR)
    except Exception:
        base = Path(__file__).resolve().parent.parent
    return base / "memory" / "history.jsonl"


def append(role: str, text: str, now: float | None = None) -> None:
    """Record one turn. Never raises: losing a line must not break a conversation."""
    text = (text or "").strip()
    if not text or role not in ("user", "assistant"):
        return
    try:
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"t": float(now if now is not None else time.time()), "role": role, "text": text[:4000]}
        with _lock:
            if path.exists() and path.stat().st_size > MAX_BYTES:
                path.replace(path.with_name(path.name + ".1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as _exc:
        _swallowed(__name__, _exc)


def _rows() -> list[dict]:
    path = history_path()
    rows: list[dict] = []
    for p in (path.with_name(path.name + ".1"), path):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    if isinstance(r, dict) and r.get("text"):
                        rows.append(r)
                except ValueError:
                    continue
        except OSError:
            continue
    return rows


def _words(q: str) -> list[str]:
    return [w for w in re.findall(r"\w+", (q or "").lower()) if len(w) > 1]


def search(query: str, limit: int = 8, days: float | None = None, now: float | None = None) -> list[dict]:
    """Turns containing every word of `query` (most recent first). With no query,
    the latest turns. `days` limits how far back to look."""
    now = now if now is not None else time.time()
    words = _words(query)
    out = []
    for r in reversed(_rows()):
        if days is not None and now - float(r.get("t", 0)) > days * 86400:
            break
        low = str(r["text"]).lower()
        if all(w in low for w in words):
            out.append(r)
            if len(out) >= max(1, min(int(limit), 30)):
                break
    return out


def format_rows(rows: list[dict]) -> str:
    if not rows:
        return "I found nothing like that in our past conversations."
    lines = []
    for r in rows:
        stamp = time.strftime("%b %d %H:%M", time.localtime(float(r.get("t", 0))))
        who = "You" if r.get("role") == "user" else "I"
        text = " ".join(str(r["text"]).split())
        lines.append(f"[{stamp}] {who}: {text[:220]}")
    return "\n".join(lines)
