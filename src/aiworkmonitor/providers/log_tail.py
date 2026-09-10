from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


class JsonlTail:
    def __init__(self, pattern: str, max_text: int = 2_000) -> None:
        self.pattern = pattern
        self.max_text = max_text
        self._offsets: dict[Path, int] = {}

    def latest_file(self) -> Path | None:
        candidates = [Path(value) for value in glob.glob(self.pattern, recursive=True)]
        candidates = [value for value in candidates if value.is_file()]
        return max(candidates, key=lambda value: value.stat().st_mtime, default=None)

    def poll(self) -> list[dict[str, Any]]:
        path = self.latest_file()
        if path is None:
            return []
        size = path.stat().st_size
        if path not in self._offsets:
            self._offsets[path] = max(size - 16_384, 0)
        offset = min(self._offsets[path], size)
        events: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                if offset:
                    handle.readline()
                for line in handle:
                    parsed = self._parse(line)
                    if parsed:
                        events.append(parsed)
                self._offsets[path] = handle.tell()
        except OSError:
            return []
        return events[-20:]

    def _parse(self, line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return None
        event_type = str(value.get("type", "event"))
        message = value.get("message", value)
        role = message.get("role") if isinstance(message, dict) else None
        content = message.get("content") if isinstance(message, dict) else message
        text = self._content_text(content)
        if not text:
            return None
        return {"kind": event_type, "role": role, "text": text[: self.max_text], "sourceFile": str(self.latest_file())}

    @staticmethod
    def _content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
            return "\n".join(chunks)
        return ""

