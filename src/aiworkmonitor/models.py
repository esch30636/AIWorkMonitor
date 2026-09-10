from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Envelope(BaseModel):
    type: str
    deviceId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now)


class CommandPayload(BaseModel):
    target: Literal["claude-code"]
    command: str = Field(min_length=1, max_length=16_000)
    requestId: str = Field(min_length=1, max_length=128)

