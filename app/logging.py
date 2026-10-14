import json
import platform as _platform
import time
import uuid
from datetime import datetime, timezone


def log_event(
    event_id: str | None = None,
    action_name: str = "unknown",
    duration_ms: float | None = None,
    failure_reason: str | None = None,
    platform: str | None = None,
    model_used: str | None = None,
    **extra,
) -> str:
    """Emit a compact, structured JSON log record without changing runtime flow."""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id or f"evt-{uuid.uuid4().hex[:12]}",
        "action_name": action_name,
        "duration_ms": float(duration_ms) if duration_ms is not None else None,
        "failure_reason": failure_reason,
        "platform": platform or _platform.system() or "unknown",
        "model_used": model_used,
    }
    payload.update(extra)
    message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(message)
    return message


__all__ = ["log_event"]
