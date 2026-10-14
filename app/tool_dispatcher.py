"""Central place for runtime tool dispatch orchestration."""


class ToolDispatcher:
    """Dispatch function calls to the active runtime session manager."""

    def __init__(self, session_manager=None):
        self.session_manager = session_manager

    def dispatch(self, function_call):
        if self.session_manager is None:
            return None
        if hasattr(self.session_manager, "_execute_tool"):
            return self.session_manager._execute_tool(function_call)
        return {"result": "Done."}


__all__ = ["ToolDispatcher"]
