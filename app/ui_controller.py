"""UI orchestration helpers for state/log updates."""
from core.diag import swallowed as _swallowed


class UIController:
    """Thin adapter around the existing Qt UI object."""

    def __init__(self, ui=None):
        self.ui = ui

    def set_state(self, state: str):
        if self.ui is not None:
            try:
                self.ui.set_state(state)
            except Exception as _exc:
                _swallowed(__name__, _exc)

    def write_log(self, message: str):
        if self.ui is not None:
            try:
                self.ui.write_log(message)
            except Exception as _exc:
                _swallowed(__name__, _exc)

    def show_content(self, title: str, body: str):
        if self.ui is not None:
            try:
                self.ui.show_content(title, body)
            except Exception as _exc:
                _swallowed(__name__, _exc)


__all__ = ["UIController"]
