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


class SharedMemoryBudget:
    """Thread-safe shared RAM budget across one or more BoundedMemoryCache instances (R62-8)."""

    def __init__(self, max_bytes: Optional[int] = None):
        self.max_bytes = max_bytes or settings.RAM_CACHE_MAX_BYTES
        self._lock = threading.RLock()
        self._caches: List["BoundedMemoryCache"] = []

    def register(self, cache: "BoundedMemoryCache") -> None:
        with self._lock:
            if cache not in self._caches:
                self._caches.append(cache)

    def current_bytes(self) -> int:
        with self._lock:
            return sum(c._current_bytes for c in self._caches)

    def evict_if_needed(self, incoming_bytes: int) -> bool:
        """
        Ensures `current_bytes + incoming_bytes <= max_bytes` by purging expired entries
        and evicting oldest LRU items across sibling caches. Returns False if impossible.
        """
        with self._lock:
            if incoming_bytes > self.max_bytes:
                return False
            now = time.time()
            for c in self._caches:
                with c._lock:
                    c._purge_expired(now)
            while self.current_bytes() + incoming_bytes > self.max_bytes:
                # Pick the cache with the oldest least-recently-used item
                victim_cache = None
                oldest_exp = float("inf")
                for c in self._caches:
                    with c._lock:
                        if c._entries:
                            _, first_entry = next(iter(c._entries.items()))
                            if first_entry.expires_at < oldest_exp:
                                oldest_exp = first_entry.expires_at
                                victim_cache = c
                if victim_cache is None:
                    break
                with victim_cache._lock:
                    if victim_cache._entries:
                        _, oldest_entry = victim_cache._entries.popitem(last=False)
                        victim_cache._current_bytes = max(0, victim_cache._current_bytes - oldest_entry.size_bytes)
            return (self.current_bytes() + incoming_bytes) <= self.max_bytes

    def admit_batch(
        self,
        items: List[Tuple["BoundedMemoryCache", str, Any]],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Atomically admits a logically linked group of (cache, key, value) entries under a single
        shared RAM budget (R63-1). Either ALL entries are retained simultaneously within budget or
        ALL batch entries are removed and False is returned without leaving orphaned references.
        """
        if not items:
            return True
        with self._lock:
            sizes = [estimate_size(val) for _, _, val in items]
            total_incoming = sum(sizes)
            if total_incoming > self.max_bytes:
                return False
            for (c, _, _), sz in zip(items, sizes):
                if sz > c.max_bytes:
                    return False

            now = time.time()
            # Reclaim space from any prior value of the exact same keys being replaced, then purge expired
            reclaimable = 0
            for c, k, _ in items:
                with c._lock:
                    c._purge_expired(now)
                    old = super(ExpiringOrderedDict, c._entries).get(k)
                    if old is not None:
                        reclaimable += old.size_bytes

            net_needed = max(0, total_incoming - reclaimable)
            if not self.evict_if_needed(net_needed):
                return False

            protected: set = set()
            inserted_ok = True
            for c, k, val in items:
                ok = c.set(k, val, ttl_seconds=ttl_seconds)
                if not ok:
                    inserted_ok = False
                    break
                protected.add((id(c), k))

            # Post-condition: ALL entries MUST coexist simultaneously without mutual eviction or budget overflow
            if inserted_ok and len(protected) == len(items) and self.current_bytes() <= self.max_bytes:
                all_present = True
                for c, k, _ in items:
                    if c.get(k) is None:
                        all_present = False
                        break
                if all_present:
                    return True

            # Roll back entire batch on partial eviction/budget shrink/failure
            for c, k, _ in items:
                c.delete(k)
            return False


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
        max_entries: Optional[int] = None,
        shared_budget: Optional[SharedMemoryBudget] = None,
    ):
        self.ttl_seconds = ttl_seconds or settings.RAM_CACHE_TTL_SECONDS
        self.max_bytes = max_bytes or settings.RAM_CACHE_MAX_BYTES
        self.max_entries = max_entries or settings.RAM_CACHE_MAX_ENTRIES
        self.shared_budget = shared_budget
        self._entries: ExpiringOrderedDict = ExpiringOrderedDict(self)
        self._current_bytes: int = 0
        self._lock = threading.RLock()
        self._stopped = False
        if self.shared_budget is not None:
            self.shared_budget.register(self)
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

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        now = time.time()
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        expires_at = now + ttl
        size = estimate_size(value)

        # If a single item exceeds local cache cap, reject before touching sibling caches
        if size > self.max_bytes:
            return False

        if self.shared_budget is not None:
            with self.shared_budget._lock:
                with self._lock:
                    if key in self._entries:
                        old_entry = self._entries.pop(key)
                        self._current_bytes = max(0, self._current_bytes - old_entry.size_bytes)
                    self._purge_expired(now)
                    while (
                        self._entries
                        and (
                            len(self._entries) >= self.max_entries
                            or (self._current_bytes + size) > self.max_bytes
                        )
                    ):
                        _, oldest_entry = self._entries.popitem(last=False)
                        self._current_bytes = max(0, self._current_bytes - oldest_entry.size_bytes)

                if not self.shared_budget.evict_if_needed(size):
                    return False

                with self._lock:
                    self._entries[key] = CacheEntry(value, expires_at, size)
                    self._current_bytes += size
                    return True

        with self._lock:
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

            self._entries[key] = CacheEntry(value, expires_at, size)
            self._current_bytes += size
            return True

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

# Global shared RAM budget & singleton cache instances (R62-8)
shared_ram_budget = SharedMemoryBudget(max_bytes=settings.RAM_CACHE_MAX_BYTES)
idempotent_result_cache = BoundedMemoryCache(shared_budget=shared_ram_budget)
