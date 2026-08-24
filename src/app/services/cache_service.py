"""In-process TTL cache for read-heavy endpoints, to shed DB load during traffic spikes."""
import threading
import time
from typing import Any, Callable, Hashable


class TTLCache:
    """Thread-safe in-memory cache with per-entry expiry. Values must be
    fully detached from the DB session (e.g. Pydantic models, not ORM objects)."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._store: dict[Hashable, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            cached = self._store.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

        value = compute()
        with self._lock:
            self._store[key] = (now + self._ttl_seconds, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
