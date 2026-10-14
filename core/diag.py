"""
core/diag.py: a place for the errors the app used to swallow.

Across the project, `except Exception: pass` appeared well over a hundred times.
That is sometimes right (a tooltip failing to update is not worth a dialog) but it
meant that when something genuinely broke, nothing anywhere said so. Those
handlers now call swallowed(), which keeps the program running exactly as before
and writes one line to memory/debug.log so the cause can be found afterwards.

Repeats of the same error are collapsed, the file is size-capped, and nothing
here can raise.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

_MAX_BYTES = 512 * 1024
_REPEAT_WINDOW = 10.0
_lock = threading.Lock()
_last: dict[tuple, float] = {}
_ECHO = bool(os.environ.get("JARVIS_DEBUG"))


def log_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent.parent
    return base / "memory" / "debug.log"


def swallowed(where: str, exc: BaseException) -> None:
    try:
        key = (where, type(exc).__name__, str(exc)[:80])
        now = time.monotonic()
        with _lock:
            if now - _last.get(key, -1e9) < _REPEAT_WINDOW:
                return
            _last[key] = now
            if len(_last) > 500:
                _last.clear()
            tb = traceback.extract_tb(exc.__traceback__)
            site = f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{where}] {type(exc).__name__}: {exc} ({site})\n"
            if _ECHO:
                sys.stderr.write(line)
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                path.replace(path.with_name("debug.log.1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        pass
