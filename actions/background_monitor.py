"""
BackgroundMonitor — user-configured topic watching.
Checks DDG news once per day per topic; alerts JARVIS when a new headline appears.
No crypto, no finance, no uninvited tracking.
Also keeps a silent 2-second live view of the current screen and system state so
JARVIS can react to desktop context without asking the user to repeat it.
"""
from core.diag import swallowed as _swallowed
import hashlib
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from actions.system_monitor import get_system_status


# ── Blocked categories (never monitor regardless of what user says) ────────────

_BLOCKED = {
    # Brand / asset names — spelled the same in every language
    "bitcoin", "ethereum", "dogecoin", "solana", "binance",
    "nft", "blockchain", "defi", "altcoin", "memecoin", "coin", "token",
    # spellings of the "crypto" root across different languages
    "crypto", "kripto", "cripto", "krypto", "крипто", "仮想通貨", "暗号資産",
    "cryptocurrency",
}

def _is_blocked(topic: str) -> bool:
    t = topic.lower()
    return any(word in t for word in _BLOCKED)


# ── Slug / hash helpers ────────────────────────────────────────────────────────

def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", topic.lower().strip())[:40].strip("_")

def _title_hash(title: str) -> str:
    return hashlib.md5(title.encode("utf-8", errors="ignore")).hexdigest()[:12]


_SCREEN_MONITOR_INTERVAL = 2.0
_LATEST_SCREEN_STATE: dict = {}
_SCREEN_MONITOR_LOCK = threading.Lock()
_SCREEN_MONITOR_THREAD: threading.Thread | None = None
_SCREEN_MONITOR_STOP = threading.Event()


def _capture_screenshot_bytes() -> bytes | None:
    """Capture a PNG screenshot without exposing it to the user unless needed."""
    try:
        import pyautogui
        buf = __import__("io").BytesIO()
        pyautogui.screenshot().save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def collect_screen_state() -> dict:
    """Return the latest screen + system snapshot. 2-second cadence is enough to
    stay current while avoiding a noisy, constant full-screen telemetry loop."""
    state = get_system_status()
    state.update({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "interval_seconds": _SCREEN_MONITOR_INTERVAL,
        "screen_size": None,
        "cursor_position": None,
        "screenshot_bytes": _capture_screenshot_bytes(),
    })
    try:
        import pyautogui
        state["screen_size"] = list(pyautogui.size())
        state["cursor_position"] = list(pyautogui.position())
    except Exception as _exc:
        _swallowed(__name__, _exc)
    return state


def latest_screen_state() -> dict:
    with _SCREEN_MONITOR_LOCK:
        return dict(_LATEST_SCREEN_STATE)


def start_screen_monitor(interval_seconds: float = 2.0, on_update=None) -> dict:
    """Run the passive screen monitor in the background once per process."""
    global _SCREEN_MONITOR_INTERVAL, _SCREEN_MONITOR_THREAD, _LATEST_SCREEN_STATE, _SCREEN_MONITOR_STOP

    _SCREEN_MONITOR_INTERVAL = max(1.0, float(interval_seconds))
    _SCREEN_MONITOR_STOP.clear()

    def _worker():
        while not _SCREEN_MONITOR_STOP.is_set():
            state = collect_screen_state()
            with _SCREEN_MONITOR_LOCK:
                _LATEST_SCREEN_STATE = state
            if on_update is not None:
                try:
                    on_update(state)
                except Exception as _exc:
                    _swallowed(__name__, _exc)
            _SCREEN_MONITOR_STOP.wait(_SCREEN_MONITOR_INTERVAL)

    with _SCREEN_MONITOR_LOCK:
        if _SCREEN_MONITOR_THREAD is not None and _SCREEN_MONITOR_THREAD.is_alive():
            return latest_screen_state()
        _LATEST_SCREEN_STATE = collect_screen_state()
        _SCREEN_MONITOR_THREAD = threading.Thread(target=_worker, daemon=True, name="xyrus-screen-monitor")
        _SCREEN_MONITOR_THREAD.start()

    return latest_screen_state()


def stop_screen_monitor() -> None:
    global _SCREEN_MONITOR_THREAD
    _SCREEN_MONITOR_STOP.set()
    if _SCREEN_MONITOR_THREAD is not None and _SCREEN_MONITOR_THREAD.is_alive():
        _SCREEN_MONITOR_THREAD.join(timeout=1.0)
    _SCREEN_MONITOR_THREAD = None


# ── Memory I/O ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    from memory.memory_manager import load_memory
    data = load_memory().get("monitors", {})
    return data if isinstance(data, dict) else {}

def _save(monitors: dict) -> None:
    from memory.memory_manager import load_memory, MEMORY_PATH, _lock
    memory = load_memory()
    memory["monitors"] = monitors
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ── Public API ─────────────────────────────────────────────────────────────────

def add_monitor(topic: str) -> str:
    topic = topic.strip()
    if not topic:
        return "Please specify a topic to monitor."
    if _is_blocked(topic):
        return "I don't monitor crypto or financial topics."
    monitors = _load()
    slug = _slug(topic)
    if slug in monitors:
        return f"Already monitoring: {monitors[slug]['topic']}"
    monitors[slug] = {
        "topic":      topic,
        "added":      datetime.now().strftime("%Y-%m-%d"),
        "last_check": "",
        "last_hash":  "",
    }
    _save(monitors)
    print(f"[Monitor] ➕ Added: {topic}")
    return f"Now monitoring: {topic}"


def remove_monitor(topic: str) -> str:
    topic = topic.strip().lower()
    monitors = _load()
    # exact slug match first
    slug = _slug(topic)
    if slug in monitors:
        label = monitors.pop(slug)["topic"]
        _save(monitors)
        return f"Stopped monitoring: {label}"
    # partial match fallback
    for key, val in list(monitors.items()):
        if topic in val.get("topic", "").lower():
            label = monitors.pop(key)["topic"]
            _save(monitors)
            return f"Stopped monitoring: {label}"
    return f"Not found in monitored topics: {topic}"


def list_monitors() -> list[str]:
    return [v.get("topic", k) for k, v in _load().items()]


def check_all() -> list[str]:
    """
    Run all pending topic checks (once per day per topic).
    Returns a list of [MONITOR_ALERT] strings — empty if nothing new.
    """
    from actions.web_search import _ddg_news

    monitors = _load()
    if not monitors:
        return []

    today   = datetime.now().strftime("%Y-%m-%d")
    alerts  = []
    changed = False

    for slug, data in monitors.items():
        if data.get("last_check") == today:
            continue                     # already checked today

        topic = data.get("topic", slug)
        try:
            results = _ddg_news(topic, max_results=5)
            if not results:
                monitors[slug]["last_check"] = today
                changed = True
                continue

            top   = results[0]
            title = top.get("title", "").strip()
            if not title:
                continue

            h = _title_hash(title)
            monitors[slug]["last_check"] = today
            changed = True

            if h == data.get("last_hash"):
                continue                 # same headline as last check — no alert

            monitors[slug]["last_hash"] = h

            snippet = top.get("snippet", "")[:150]
            source  = top.get("source", "")
            parts   = [f"[MONITOR_ALERT] {topic}", f"Headline: {title}"]
            if snippet:
                parts.append(snippet)
            if source:
                parts.append(f"Source: {source}")
            alerts.append("\n".join(parts))
            print(f"[Monitor] 🔔 New headline for '{topic}': {title[:60]}")

        except Exception as e:
            print(f"[Monitor] ⚠️ Check failed for '{topic}': {e}")

    if changed:
        _save(monitors)

    return alerts
