"""AI orchestration service for model selection and prompt assembly."""

from __future__ import annotations


class AIOrchestrationService:
    """Stable wrapper around the runtime's live-AI model configuration."""

    def __init__(self, model: str = "models/gemini-3.1-flash-live-preview"):
        self.model = model
        self._history: list[str] = []

    def build_system_instruction(self, *, name: str = "Xyrus", capabilities: str = "") -> str:
        """Return a minimal system prompt for the model."""
        base = (
            f"You are {name}. Be concise, direct, and use the tools you have available. "
            "Never invent results."
        )
        if capabilities:
            return f"{base}\nCapabilities:\n{capabilities}"
        return base

    def record_turn(self, content: str) -> None:
        if content:
            self._history.append(content)

    def recent_turns(self, limit: int = 10) -> list[str]:
        return self._history[-limit:]

    def switch_model(self, model: str) -> str:
        self.model = model
        return self.model


__all__ = ["AIOrchestrationService"]
