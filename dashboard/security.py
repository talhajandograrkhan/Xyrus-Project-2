"""
dashboard/security.py: two small guards for the phone dashboard.

The dashboard listens on every network interface so a phone can reach it, which
means anyone on the same WiFi can reach the login page too. Two things were
missing:

  RateLimiter  the pairing key is 6 characters and could be guessed at without
               any limit on how fast; now five wrong tries lock that address out.
  TokenStore   a signed-in phone kept its token forever, and the list of tokens
               only ever grew; now a token lapses after `ttl` seconds.

Both are plain Python with an injectable clock, so they are tested without a
network.
"""
from __future__ import annotations

import time
from typing import Callable, Optional


class RateLimiter:
    """Lock an address out after too many failures inside a window."""

    def __init__(self, max_failures: int = 5, window: float = 60.0, lockout: float = 300.0,
                 clock: Callable[[], float] = time.monotonic):
        self.max_failures, self.window, self.lockout = max_failures, window, lockout
        self._clock = clock
        self._fails: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def blocked(self, who: str) -> float:
        """Seconds left on the lockout, or 0.0 when this address may try."""
        now = self._clock()
        until = self._locked_until.get(who, 0.0)
        if until > now:
            return until - now
        if until:
            self._locked_until.pop(who, None)
        return 0.0

    def failure(self, who: str) -> None:
        now = self._clock()
        recent = [t for t in self._fails.get(who, []) if now - t < self.window]
        recent.append(now)
        self._fails[who] = recent
        if len(recent) >= self.max_failures:
            self._locked_until[who] = now + self.lockout
            self._fails.pop(who, None)
        if len(self._fails) > 2000:                       # never grow without bound
            self._fails = {k: v for k, v in self._fails.items() if v and now - v[-1] < self.window}

    def success(self, who: str) -> None:
        self._fails.pop(who, None)
        self._locked_until.pop(who, None)


class TokenStore:
    """A set of auth tokens that expire. Supports the few set operations the
    server uses: add, `in`, discard, clear and len."""

    def __init__(self, ttl: float = 12 * 3600.0, on_expire: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self._on_expire = on_expire
        self._clock = clock
        self._until: dict[str, float] = {}

    def add(self, token: str) -> None:
        self._prune()
        self._until[token] = self._clock() + self.ttl

    def __contains__(self, token) -> bool:
        until = self._until.get(token)
        if until is None:
            return False
        if until <= self._clock():
            self._drop(token)
            return False
        return True

    def discard(self, token: str) -> None:
        self._until.pop(token, None)

    def clear(self) -> None:
        self._until.clear()

    def __len__(self) -> int:
        self._prune()
        return len(self._until)

    def _drop(self, token: str) -> None:
        self._until.pop(token, None)
        if self._on_expire:
            try:
                self._on_expire(token)
            except Exception:
                pass

    def _prune(self) -> None:
        now = self._clock()
        for t in [t for t, u in self._until.items() if u <= now]:
            self._drop(t)
