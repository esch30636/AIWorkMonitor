from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ActivityProvider(ABC):
    name: str

    @abstractmethod
    def state(self) -> dict[str, Any]:
        """Return a cheap, serializable provider state snapshot."""

    @abstractmethod
    def poll_events(self) -> list[dict[str, Any]]:
        """Return activity events discovered since the previous poll."""

