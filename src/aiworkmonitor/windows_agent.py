from __future__ import annotations

import argparse
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from aiworkmonitor import __version__
from aiworkmonitor.agent import DesktopAgent
from aiworkmonitor.collectors.system import SystemCollector
from aiworkmonitor.config import AgentSettings
from aiworkmonitor.providers.chatgpt import ChatGptDesktopProvider
from aiworkmonitor.providers.claude import ClaudeCodeProvider
from aiworkmonitor.windows_runtime import executable_directory, load_config_file


LOGGER = logging.getLogger("aiworkmonitor.windows_agent")


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
    parser.add_argument("--background", action="store_true", help="Run the agent without opening the GUI")
    parser.add_argument("--check", action="store_true", help="Print config and telemetry, then exit")
    parser.add_argument("--version", action="version", version=f"AIWorkMonitor Agent {__version__}")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config.resolve() if args.config else executable_directory() / "aiworkmonitor.env"

    if os.name == "nt" and not args.background and not args.check:
        from aiworkmonitor.windows_gui import launch_windows_gui

        launch_windows_gui(config_path)
        return

    try:
        loaded = load_config_file(config_path, required=args.config is not None)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    settings = AgentSettings.from_env()
    if args.check:
        print(json.dumps(check_payload(settings), ensure_ascii=False, indent=2))
        return

    log_handlers: list[logging.Handler] = []
    if args.background:
        log_directory = executable_directory() / "logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        log_handlers.append(
            RotatingFileHandler(
                log_directory / "agent.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        )
    else:
        log_handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=log_handlers,
        force=True,
    )
    if not loaded:
        LOGGER.warning("No config file found at %s; using environment variables and defaults", config_path)

    if settings.token == "development-token":
        LOGGER.warning("AIWM_TOKEN is using the insecure development default")

    import asyncio

    try:
        asyncio.run(DesktopAgent(settings).run_forever())
    except KeyboardInterrupt:
        LOGGER.info("Agent stopped")


if __name__ == "__main__":
    main()
