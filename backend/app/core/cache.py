import time
import sys
import threading
from collections import OrderedDict
from typing import Any, Optional, Tuple, Dict, List
from app.core.config import settings

class CacheEntry:
    __slots__ = ("value", "expires_at", "size_bytes")

    def __init__(self, value: Any, expires_at: float, size_bytes: int):
        self.value = value
        self.expires_at = expires_at
        self.size_bytes = size_bytes


def estimate_size(obj: Any) -> int:
    """Estimates in-memory byte size of cached response payloads."""
    if isinstance(obj, (bytes, bytearray)):
        return len(obj)
    elif isinstance(obj, str):
        return len(obj.encode("utf-8"))
    elif isinstance(obj, tuple):
        return sum(estimate_size(x) for x in obj)
    elif isinstance(obj, list):
        return sum(estimate_size(x) for x in obj)
    elif isinstance(obj, dict):
        return sum(estimate_size(k) + estimate_size(v) for k, v in obj.items())
    return sys.getsizeof(obj)


class ExpiringOrderedDict(OrderedDict):
    """
    OrderedDict subclass that automatically purges expired entries upon any query or inspection (C06).
    Guarantees that len(cache._entries), iteration, and lookups reflect active TTL purge.
    """
    def __init__(self, owner: Any, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner = owner

    def _purge_if_needed(self):
        if self._owner is not None:
            self._owner._purge_expired(time.time())

    def __len__(self) -> int:
        self._purge_if_needed()
        return super().__len__()

    def __iter__(self):
        self._purge_if_needed()
        return super().__iter__()

    def __getitem__(self, key):
        self._purge_if_needed()
        return super().__getitem__(key)

    def __contains__(self, key):
        self._purge_if_needed()
        return super().__contains__(key)

    def get(self, key, default=None):
        self._purge_if_needed()
        return super().get(key, default)

    def items(self):
        self._purge_if_needed()
        return super().items()

    def values(self):
        self._purge_if_needed()
        return super().values()

    def keys(self):
        self._purge_if_needed()
        return super().keys()


class BoundedMemoryCache:
    """
    RAM-only bounded cache adhering to Zero Durable Retention (ADR-001 / B02 / B07 / C06):
    - Strict TTL (default: 600s / 10 minutes)
    - Strict byte budget (default: 50 MiB)
    - Maximum entries cap (default: 100)
    - Least Recently Used (LRU) eviction on memory or entry pressure
    - Active TTL expiration on idle and direct container access
    - Thread-safe synchronization
    """

    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        max_bytes: Optional[int] = None,
        max_entries: Optional[int] = None
    ):
        self.ttl_seconds = ttl_seconds or settings.RAM_CACHE_TTL_SECONDS
        self.max_bytes = max_bytes or settings.RAM_CACHE_MAX_BYTES
        self.max_entries = max_entries or settings.RAM_CACHE_MAX_ENTRIES
        self._entries: ExpiringOrderedDict = ExpiringOrderedDict(self)
        self._current_bytes: int = 0
        self._lock = threading.Lock()
        self._stopped = False
        self._sweeper_thread = threading.Thread(target=self._sweep_loop, daemon=True)
        self._sweeper_thread.start()

    def _sweep_loop(self):
        while not self._stopped:
            time.sleep(0.01)
            with self._lock:
                self._purge_expired(time.time())

    def close(self):
        self._stopped = True

    def __del__(self):
        self._stopped = True

    def _purge_expired(self, now: float) -> None:
        """Removes all expired entries from cache."""
        expired_keys = [
            k for k, entry in super(ExpiringOrderedDict, self._entries).items()
            if entry.expires_at <= now
        ]
        for k in expired_keys:
            entry = super(ExpiringOrderedDict, self._entries).pop(k, None)
            if entry:
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            now = time.time()
            entry = self._entries.get(key)
            if not entry:
                return default
            if entry.expires_at <= now:
                # Expired -> evict and return default
                self._entries.pop(key, None)
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                return default
            # Move to end for LRU order
            self._entries.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        with self._lock:
            now = time.time()
            ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
            expires_at = now + ttl
            size = estimate_size(value)

            # If existing key, remove old size first
            if key in self._entries:
                old_entry = self._entries.pop(key)
                self._current_bytes = max(0, self._current_bytes - old_entry.size_bytes)

            # Purge any expired items
            self._purge_expired(now)

            # Evict oldest (LRU) until within budget
            while (
                self._entries
                and (
                    len(self._entries) >= self.max_entries
                    or (self._current_bytes + size) > self.max_bytes
                )
            ):
                _, oldest_entry = self._entries.popitem(last=False)
                self._current_bytes = max(0, self._current_bytes - oldest_entry.size_bytes)

            # If a single item is larger than the total budget, do not cache it
            if size > self.max_bytes:
                return

            self._entries[key] = CacheEntry(value, expires_at, size)
            self._current_bytes += size

    def delete(self, key: str) -> None:
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry:
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry:
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                return entry.value
            return default

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._current_bytes = 0

    def values(self) -> List[Any]:
        with self._lock:
            self._purge_expired(time.time())
            return [entry.value for entry in self._entries.values()]

    def items(self) -> List[Tuple[str, Any]]:
        with self._lock:
            self._purge_expired(time.time())
            return [(k, entry.value) for k, entry in self._entries.items()]

    def keys(self) -> List[str]:
        with self._lock:
            self._purge_expired(time.time())
            return list(self._entries.keys())

    def __contains__(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            entry = self._entries.get(key)
            if not entry:
                return False
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                self._current_bytes = max(0, self._current_bytes - entry.size_bytes)
                return False
            return True

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired(time.time())
            return len(self._entries)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._purge_expired(time.time())
            return {
                "entries_count": len(self._entries),
                "current_bytes": self._current_bytes,
                "max_bytes": self.max_bytes,
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds
            }

# Global singleton instance for conversion response caching
idempotent_result_cache = BoundedMemoryCache()
