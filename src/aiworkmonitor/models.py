from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Envelope(BaseModel):
    type: str
    deviceId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now)


class CommandPayload(BaseModel):
    target: Literal["claude-code"]
    action: Literal["prompt", "compact"] = "prompt"
    command: str = Field(default="", max_length=16_000)
    requestId: str = Field(min_length=1, max_length=128)
    sessionId: str | None = Field(default=None, min_length=1, max_length=128)
    model: str = Field(default="session", min_length=1, max_length=256)
    effort: Literal["auto", "low", "medium", "high", "xhigh", "max", "ultracode"] = "auto"

    @model_validator(mode="after")
    def validate_action(self) -> "CommandPayload":
        self.command = self.command.strip()
        self.model = self.model.strip()
        if self.action == "prompt" and not self.command:
            raise ValueError("A Claude prompt cannot be empty")
        if not self.model or any(ord(character) < 32 or ord(character) == 127 for character in self.model):
            raise ValueError("Claude model contains unsupported control characters")
        return self
