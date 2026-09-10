from __future__ import annotations

from typing import Any

from .base import ActivityProvider
from .claude import _processes_matching
from .log_tail import JsonlTail


class ChatGptDesktopProvider(ActivityProvider):
    name = "chatgpt-desktop"

    def __init__(self, log_glob: str | None = None) -> None:
        self.tail = JsonlTail(log_glob) if log_glob else None

    def state(self) -> dict[str, Any]:
        processes = _processes_matching(("chatgpt", "openai.chatgpt"))
        latest = self.tail.latest_file() if self.tail else None
        return {
            "name": self.name,
            "running": bool(processes),
            "processes": processes,
            "latestActivityFile": str(latest) if latest else None,
            "mode": "configured-log" if self.tail else "process-only",
        }

    def poll_events(self) -> list[dict[str, Any]]:
        if not self.tail:
            return []
        return [{"provider": self.name, **event} for event in self.tail.poll()]
