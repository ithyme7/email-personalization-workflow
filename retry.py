from __future__ import annotations

import logging
import random
import time
from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _jitter(base_delay: float, max_jitter: float = 0.5) -> float:
    """Voeg random jitter toe om thundering herd te voorkomen."""
    return base_delay + random.uniform(0, max_jitter)


class ExponentialBackoff:
    """Non-blocking exponential backoff retry helper.

    Gebruik als context manager of direct:

        async with ExponentialBackoff(max_attempts=5) as retry:
            async for attempt in retry:
                response = await session.get(url)
                retry.maybe_retry(response.status_code)

    Of imperatief:

        backoff = ExponentialBackoff(max_attempts=5, base_delay=1.0)
        for attempt, delay in backoff.attempts():
            try:
                response = session.get(url)
                if response.status_code < 400:
                    break
                delay = backoff.retry_delay(response.status_code)
                time.sleep(delay)
            except ConnectionError:
                delay = backoff.retry_delay()
                time.sleep(delay)

    In een ThreadPoolExecutor wordt time.sleep() door de OS-scheduler
    opgepakt, waardoor andere workers de thread kunnen overnemen.
    """

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        max_attempts: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 120.0,
        jitter: bool = True,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._attempt = 0

    def retry_delay(self, status_code: int | None = None, server_retry_after: float | None = None) -> float:
        """Berekent de vertraging voor de volgende poging.

        Args:
            status_code: HTTP-statuscode (429 krijgt langer wachttijd).
            server_retry_after: Retry-After headerwaarde in seconden.
        """
        if server_retry_after is not None:
            delay = min(float(server_retry_after) + 1.0, self.max_delay)
            return delay if not self.jitter else _jitter(delay)

        # Standaard exponential backoff: base * 2^attempt
        delay = min(self.base_delay * (2 ** max(0, self._attempt - 1)), self.max_delay)

        # 429 krijgt extra tijd
        if status_code == 429:
            delay = max(delay, 5.0)

        return delay if not self.jitter else _jitter(delay)

    @property
    def should_retry(self) -> bool:
        return self._attempt < self.max_attempts

    def next_attempt(self) -> int:
        """Verhoogt de pogingsteller en retourneert het huidige attempt-nummer."""
        self._attempt += 1
        return self._attempt

    def reset(self) -> None:
        """Reset de pogingsteller."""
        self._attempt = 0

    def attempts(self) -> list[tuple[int, float]]:
        """Genereert (attempt, delay) tuples voor gebruik in een for-loop.

        Voorbeeld:
            backoff = ExponentialBackoff(max_attempts=3)
            for attempt, delay in backoff.attempts():
                try:
                    result = do_something()
                    break
                except TemporaryError:
                    time.sleep(delay)
        """
        results = []
        temp = ExponentialBackoff(
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
            max_delay=self.max_delay,
            jitter=self.jitter,
        )
        while temp.should_retry:
            attempt = temp.next_attempt()
            delay = temp.retry_delay()
            results.append((attempt, delay))
        return results

    def retry_after_delay(self, status_code: int | None = None, server_retry_after: float | None = None) -> float:
        """Berekent delay, logt, en retourneert. Verhoog interne teller."""
        attempt = self.next_attempt()
        delay = self.retry_delay(status_code, server_retry_after)
        if status_code:
            logger.info("Retry %s/%s after HTTP %s: waiting %.1fs", attempt, self.max_attempts, status_code, delay)
        else:
            logger.info("Retry %s/%s: waiting %.1fs", attempt, self.max_attempts, delay)
        return delay


def retry_with_backoff(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    retryable_statuses: frozenset[int] | None = None,
) -> Callable:
    """Decorator die een functie met retry-logica wrap't.

    De wrapped functie moet een requests.Response returneren of een exception
    gooien. De decorator behandelt retries en backoff.

    Gebruik:
        @retry_with_backoff(max_attempts=3)
        def fetch_url(url):
            return session.get(url, timeout=30)
    """
    if retryable_statuses is None:
        retryable_statuses = ExponentialBackoff.RETRYABLE_STATUS_CODES

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            backoff = ExponentialBackoff(max_attempts=max_attempts, base_delay=base_delay)
            last_exception: Exception | None = None

            while backoff.should_retry:
                attempt = backoff.next_attempt()
                try:
                    response = func(*args, **kwargs)
                    if hasattr(response, "status_code") and response.status_code in retryable_statuses:
                        delay = backoff.retry_after_delay(response.status_code)
                        time.sleep(delay)
                        last_exception = None
                        continue
                    return response
                except Exception as exc:
                    last_exception = exc
                    retryable = "RequestException" in type(exc).__name__ or "ConnectionError" in type(exc).__name__
                    if retryable and backoff.should_retry:
                        delay = backoff.retry_after_delay()
                        time.sleep(delay)
                        continue
                    raise

            if last_exception:
                raise last_exception
            raise RuntimeError(f"All {max_attempts} retry attempts exhausted")

        return wrapper

    return decorator