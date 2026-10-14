"""Memory service for basic key-value storage used by the assistant."""

from __future__ import annotations


class MemoryService:
    """Lightweight memory store with a namespace-aware API."""

    def __init__(self):
        self._store: dict[str, dict[str, object]] = {}

    def store(self, namespace: str, key: str, value: object) -> object:
        bucket = self._store.setdefault(namespace, {})
        bucket[key] = value
        return value

    def get(self, namespace: str, key: str, default=None):
        return self._store.get(namespace, {}).get(key, default)

    def delete(self, namespace: str, key: str) -> None:
        bucket = self._store.get(namespace)
        if bucket is not None:
            bucket.pop(key, None)

    def items(self, namespace: str | None = None):
        if namespace is None:
            return dict(self._store)
        return dict(self._store.get(namespace, {}))


__all__ = ["MemoryService"]
