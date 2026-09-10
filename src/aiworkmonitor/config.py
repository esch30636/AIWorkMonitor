from __future__ import annotations

import os
import platform
import socket
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RelaySettings:
    token: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> "RelaySettings":
        return cls(
            token=os.getenv("AIWM_TOKEN", "development-token"),
            host=os.getenv("AIWM_HOST", "0.0.0.0"),
            port=int(os.getenv("AIWM_PORT", "8765")),
        )


@dataclass(frozen=True)
class AgentSettings:
    token: str
    relay_url: str
    device_id: str
    device_name: str
    sample_interval: float
    allow_claude_commands: bool
    claude_workdir: Path
    claude_log_glob: str | None
    chatgpt_log_glob: str | None

    @classmethod
    def from_env(cls) -> "AgentSettings":
        hostname = socket.gethostname()
        default_workdir = Path.cwd()
        return cls(
            token=os.getenv("AIWM_TOKEN", "development-token"),
            relay_url=os.getenv("AIWM_RELAY_URL", "ws://127.0.0.1:8765").rstrip("/"),
            device_id=os.getenv("AIWM_DEVICE_ID", f"{platform.system().lower()}-{hostname}"),
            device_name=os.getenv("AIWM_DEVICE_NAME", hostname),
            sample_interval=max(float(os.getenv("AIWM_SAMPLE_INTERVAL", "2")), 0.5),
            allow_claude_commands=_bool_env("AIWM_ALLOW_CLAUDE_COMMANDS"),
            claude_workdir=Path(os.getenv("AIWM_CLAUDE_WORKDIR") or default_workdir).resolve(),
            claude_log_glob=os.getenv("AIWM_CLAUDE_LOG_GLOB") or None,
            chatgpt_log_glob=os.getenv("AIWM_CHATGPT_LOG_GLOB") or None,
        )

