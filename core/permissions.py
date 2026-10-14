"""
core/permissions.py: who gets to do what, and a record that it happened.

WHY THIS EXISTS
    core/confirm.py can park an irreversible action behind a button the model
    cannot press, but only shutdown, restart and WiFi used it. Everything else,
    including sending a message in your name, running code, and executing a
    script the model had just written, ran the moment the model asked. A web
    page or a document the assistant read could therefore talk it into
    something. This module widens the gate to the actions that deserve one, makes
    it switchable, and keeps an audit trail of every tool call.

THREE THINGS
    guard(...)        run now, ask first, or refuse, depending on the policy
    timeout_for(...)  how long the voice session will wait for a tool
    audit(...)        one JSON line per tool call, with secrets redacted

    Policy per tool is "ask" (default for risky tools), "allow" or "deny", set in
    config/api_keys.json under "tool_policies". A master switch,
    "confirm_risky", turns every "ask" into "allow" for people who prefer speed.
"""
from __future__ import annotations

from core.diag import swallowed as _swallowed
import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

# Tools the model is not allowed to hold up the conversation for forever.
DEFAULT_TIMEOUT = 90.0
TOOL_TIMEOUTS = {
    "dev_agent": 600.0, "game_updater": 600.0, "code_helper": 180.0,
    "file_processor": 180.0, "browser_control": 180.0, "flight_finder": 180.0,
    "youtube_video": 150.0, "video_player": 90.0, "web_search": 75.0,
    "send_message": 90.0, "computer_settings": 60.0, "open_app": 45.0,
    "reminder": 45.0, "weather_report": 45.0, "file_controller": 120.0,
    "desktop_control": 180.0, "computer_control": 120.0,
}

_SECRET = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|cookie)", re.I)
_AUDIT_MAX_BYTES = 2 * 1024 * 1024
_lock = threading.Lock()


def _base_dir() -> Path:
    try:
        from memory.config_manager import BASE_DIR
        return Path(BASE_DIR)
    except Exception:
        return Path(__file__).resolve().parent.parent


def audit_path() -> Path:
    return _base_dir() / "memory" / "audit.log"


def timeout_for(tool: str) -> float:
    return float(TOOL_TIMEOUTS.get(tool, DEFAULT_TIMEOUT))


# ── policy ───────────────────────────────────────────────────────────────────
def confirm_risky_enabled() -> bool:
    try:
        from memory.config_manager import get_confirm_risky
        return bool(get_confirm_risky())
    except Exception:
        return True


def tool_policy(tool: str, default: str = "ask") -> str:
    """'ask' | 'allow' | 'deny' for one tool."""
    try:
        from memory.config_manager import get_tool_policies
        mode = str((get_tool_policies() or {}).get(tool, "")).lower().strip()
    except Exception:
        mode = ""
    return mode if mode in ("ask", "allow", "deny") else default


def is_denied(tool: str) -> bool:
    return tool_policy(tool, default="allow") == "deny"


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def guard(tool: str, title: str, detail: str, run: Callable[[], str], key: str | None = None) -> str:
    """Run `run` now, or put it behind the on-screen confirmation, or refuse."""
    mode = tool_policy(tool, default="ask")
    if mode == "deny":
        audit(tool, {"title": title}, "denied", 0.0)
        return f"{title} is switched off in the user's settings, so it was not done. Tell them plainly."
    if mode == "allow" or not confirm_risky_enabled():
        return run() or "Done."

    from core import confirm
    waiting = confirm.pending_title()
    if waiting:
        return (f"Another confirmation is still waiting on screen ('{waiting}'). "
                f"Ask the user to answer it first. Nothing was done.")

    def _confirmed() -> str:
        t0 = time.perf_counter()
        try:
            out = run() or "Done."
            audit(tool, {"title": title}, "confirmed", (time.perf_counter() - t0) * 1000.0)
            return str(out)[:300]
        except Exception as e:
            audit(tool, {"title": title}, f"confirmed-failed: {e}", (time.perf_counter() - t0) * 1000.0)
            raise

    return confirm.request(key or f"tool-{tool}", title, _clip(detail, 600), _confirmed)


# ── audit ────────────────────────────────────────────────────────────────────
def _redact(value, depth: int = 0):
    if depth > 3:
        return "\u2026"
    if isinstance(value, dict):
        return {str(k): ("***" if _SECRET.search(str(k)) else _redact(v, depth + 1))
                for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in list(value)[:10]]
    if isinstance(value, str):
        return _clip(value, 160)
    return value


def audit(tool: str, args, outcome: str, duration_ms: float) -> None:
    """Append one line to memory/audit.log. Never raises."""
    try:
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "tool": tool,
               "args": _redact(args), "outcome": _clip(outcome, 160),
               "ms": int(duration_ms)}
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            if path.exists() and path.stat().st_size > _AUDIT_MAX_BYTES:
                path.replace(path.with_suffix(".log.1"))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as _exc:
        _swallowed(__name__, _exc)


def recent_audit(limit: int = 20) -> list[dict]:
    try:
        lines = audit_path().read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []
