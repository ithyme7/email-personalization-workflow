from __future__ import annotations

import threading
import time

logger = __import__("logging").getLogger(__name__)


class RateLimiter:
    """Thread-safe token-bucket rate limiter voor LLM API-calls.

    Toegestane piek: `max_requests` tegelijk (burst).
    Gemiddelde snelheid: `max_requests` per `window_seconds`.

    Gebruik:
        limiter = RateLimiter(max_requests=20, window_seconds=60.0)
        # In worker-thread:
        with limiter:
            response = session.post(url, ...)

    Of imperatief:
        limiter.acquire()
        try:
            response = session.post(url, ...)
        finally:
            pass  # token is verbruikt
    """

    def __init__(self, max_requests: int = 20, window_seconds: float = 60.0) -> None:
        if max_requests <= 0:
            raise ValueError(f"max_requests must be > 0, got {max_requests}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be > 0, got {window_seconds}")

        self._max_requests = max_requests
        self._window = window_seconds
        self._tokens: float = max_requests
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._total_acquired = 0

    def _refill(self) -> None:
        """Voeg tokens toe op basis van verstreken tijd sinds laatste refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self._max_requests / self._window)
        if new_tokens >= 1.0:
            added = int(new_tokens)
            self._tokens = min(float(self._max_requests), self._tokens + added)
            self._last_refill = now

    def acquire(self, blocking: bool = True, timeout: float | None = None) -> bool:
        """Wacht tot een token beschikbaar is en consumeer het.

        Args:
            blocking: Als False, return direct False als geen token beschikbaar.
            timeout: Maximale wachttijd in seconden (None = oneindig wachten).

        Returns:
            True als een token is verkregen, False anders.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        with self._lock:
            if not blocking:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_acquired += 1
                    return True
                return False

            while True:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_acquired += 1
                    return True

                # Bereken hoe lang we moeten wachten op het volgende token
                wait = (1.0 - self._tokens) * (self._window / self._max_requests)
                wait = max(wait, 0.01)  # Minimaal 10ms om CPU-spinning te voorkomen

                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    wait = min(wait, remaining)

                self._condition.wait(wait)

    def total_acquired(self) -> int:
        """Totaal aantal verkregen tokens sinds creatie."""
        with self._lock:
            return self._total_acquired

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(self, *_) -> None:
        pass