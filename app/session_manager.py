"""Session lifecycle orchestration for the assistant runtime."""

from __future__ import annotations

from app.model_connection import ModelConnection


class SessionManager:
    """Thin runtime boundary that keeps the session logic separate from boot logic."""

    def __init__(self, ui=None):
        self.ui = ui
        self.model_connection = ModelConnection()
        self.session = None

    def start(self):
        return self

    async def run(self):
        raise NotImplementedError("SessionManager.run() must be implemented by the runtime class.")


class JarvisLive(SessionManager):
    """Compatibility wrapper around the existing application runtime."""

    def __init__(self, ui=None):
        super().__init__(ui=ui)


__all__ = ["JarvisLive", "SessionManager"]
