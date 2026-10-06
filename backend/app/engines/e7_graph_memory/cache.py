"""Cache backend for Graph Memory.

SH.docx §2 specifies Redis for retained labels. The prototype runs without
external infrastructure (constraint C4), so this is an in-process LRU behind
a deliberately narrow interface — ``get``/``set``/``delete``/``clear``.
Swapping in Redis later means implementing four methods, with no change to
engine logic.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Dict, Optional

DEFAULT_MAX_ENTRIES = 5000


class MemoryCache(ABC):
    """The only surface Graph Memory depends on."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def stats(self) -> Dict[str, int]: ...


class InProcessCache(MemoryCache):
    """Thread-safe LRU cache.

    Bounded so a long demo run cannot grow memory without limit; the least
    recently used entry is evicted once the cap is reached.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")

        self._max_entries = max_entries
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._data:
                self._misses += 1
                return None

            self._data.move_to_end(key)
            self._hits += 1
            return self._data[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value

            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = self._misses = self._evictions = 0

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._data),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
