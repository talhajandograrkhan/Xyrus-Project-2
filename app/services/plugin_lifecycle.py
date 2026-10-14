"""Plugin lifecycle service for registration and startup tracking."""

from __future__ import annotations


class PluginLifecycleService:
    """Tracks plugin registrations and lifecycle state in a compact registry."""

    def __init__(self):
        self._plugins: dict[str, dict[str, object]] = {}

    def register(self, plugin_name: str, *, enabled: bool = True) -> dict[str, object]:
        plugin = {"name": plugin_name, "enabled": enabled, "loaded": True}
        self._plugins[plugin_name] = plugin
        return plugin

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    def is_loaded(self, plugin_name: str) -> bool:
        plugin = self._plugins.get(plugin_name)
        return bool(plugin and plugin.get("loaded"))

    def unload(self, plugin_name: str) -> bool:
        plugin = self._plugins.get(plugin_name)
        if plugin is None:
            return False
        plugin["loaded"] = False
        return True


__all__ = ["PluginLifecycleService"]
