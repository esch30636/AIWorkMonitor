from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from aiworkmonitor import __version__
from aiworkmonitor.agent import DesktopAgent
from aiworkmonitor.collectors.system import SystemCollector
from aiworkmonitor.config import AgentSettings
from aiworkmonitor.providers.chatgpt import ChatGptDesktopProvider
from aiworkmonitor.providers.claude import ClaudeCodeProvider


LOGGER = logging.getLogger("aiworkmonitor.windows_agent")


def executable_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def load_config_file(path: Path, *, required: bool = False) -> bool:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Config file does not exist: {path}")
        return False

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key.startswith("AIWM_"):
            raise ValueError(f"Invalid config line {line_number}: unsupported key {key!r}")
        os.environ.setdefault(key, value)

    workdir = os.getenv("AIWM_CLAUDE_WORKDIR")
    if workdir and not Path(workdir).is_absolute():
        os.environ["AIWM_CLAUDE_WORKDIR"] = str((path.parent / workdir).resolve())
    return True


def check_payload(settings: AgentSettings) -> dict[str, Any]:
    collector = SystemCollector()
    providers = [
        ClaudeCodeProvider(settings.claude_log_glob),
        ChatGptDesktopProvider(settings.chatgpt_log_glob),
    ]
    return {
        "version": __version__,
        "config": {
            "relayUrl": settings.relay_url,
            "deviceId": settings.device_id,
            "deviceName": settings.device_name,
            "sampleInterval": settings.sample_interval,
            "claudeCommands": settings.allow_claude_commands,
            "claudeWorkdir": str(settings.claude_workdir),
            "tokenConfigured": settings.token != "development-token",
        },
        "telemetry": collector.sample(),
        "providers": {provider.name: provider.state() for provider in providers},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIWorkMonitor Windows desktop agent")
    parser.add_argument("--config", type=Path, help="Path to an aiworkmonitor.env file")
    parser.add_argument("--check", action="store_true", help="Print config and telemetry, then exit")
    parser.add_argument("--version", action="version", version=f"AIWorkMonitor Agent {__version__}")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    config_path = args.config.resolve() if args.config else executable_directory() / "aiworkmonitor.env"
    try:
        loaded = load_config_file(config_path, required=args.config is not None)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    if not loaded:
        LOGGER.warning("No config file found at %s; using environment variables and defaults", config_path)

    settings = AgentSettings.from_env()
    if args.check:
        print(json.dumps(check_payload(settings), ensure_ascii=False, indent=2))
        return

    if settings.token == "development-token":
        LOGGER.warning("AIWM_TOKEN is using the insecure development default")

    import asyncio

    try:
        asyncio.run(DesktopAgent(settings).run_forever())
    except KeyboardInterrupt:
        LOGGER.info("Agent stopped")


if __name__ == "__main__":
    main()
