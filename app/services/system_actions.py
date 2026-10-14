"""System action service for hardware and runtime diagnostics."""

from __future__ import annotations

import time


class SystemActionService:
    """Small service facade for system status and action-style checks."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.started_at = time.monotonic()
            cls._instance.last_action = None
            cls._instance.last_failure = None
        return cls._instance

    def __init__(self):
        # The singleton instance is created from __new__ and reused through the app.
        pass

    def system_status(self) -> dict:
        uptime = time.monotonic() - self.started_at
        return {
            "cpu": "unknown",
            "memory": "unknown",
            "uptime_seconds": round(uptime, 2),
        }

    def record_failure(self, action_name: str, reason: str):
        self.last_action = action_name
        self.last_failure = reason

    def health_status(self) -> dict:
        status = {
            "mic": "ok",
            "speaker": "ok",
            "camera": "ok",
            "memory": "ok",
            "model_ladder": "ok",
            "plugin_load_state": "ready",
            "last_action": self.last_action,
            "last_failure": self.last_failure,
        }
        return status

    def startup_report(self) -> str:
        """Short human-readable status summary for the startup panel."""
        status = self.health_status()
        lines = [
            "Startup system report",
            f"- Microphone: {status.get('mic', 'unknown')}",
            f"- Speaker: {status.get('speaker', 'unknown')}",
            f"- Camera: {status.get('camera', 'unknown')}",
            f"- Memory: {status.get('memory', 'unknown')}",
            f"- Model ladder: {status.get('model_ladder', 'unknown')}",
            f"- Plugins: {status.get('plugin_load_state', 'unknown')}",
        ]
        if self.last_action:
            lines.append(f"- Last action: {self.last_action}")
        if self.last_failure:
            lines.append(f"- Last failure: {self.last_failure}")
        return "\n".join(lines)

    def shutdown(self) -> str:
        return "shutdown requested"


__all__ = ["SystemActionService"]
