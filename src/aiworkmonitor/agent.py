from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import urllib.parse
from typing import Any

import websockets

from .collectors.system import SystemCollector
from .config import AgentSettings
from .models import CommandPayload, Envelope
from .providers.base import ActivityProvider
from .providers.chatgpt import ChatGptDesktopProvider
from .providers.claude import ClaudeCodeProvider, ClaudeCommandRunner

LOGGER = logging.getLogger("aiworkmonitor.agent")


class DesktopAgent:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.collector = SystemCollector()
        self.providers: list[ActivityProvider] = [
            ClaudeCodeProvider(settings.claude_log_glob),
            ChatGptDesktopProvider(settings.chatgpt_log_glob),
        ]
        self.command_runner = ClaudeCommandRunner(settings.allow_claude_commands, settings.claude_workdir)

    @property
    def websocket_url(self) -> str:
        device = urllib.parse.quote(self.settings.device_id, safe="")
        token = urllib.parse.quote(self.settings.token, safe="")
        return f"{self.settings.relay_url}/ws/agent/{device}?token={token}"

    async def run_forever(self) -> None:
        attempt = 0
        while True:
            try:
                async with websockets.connect(self.websocket_url, max_size=2**21, ping_interval=20) as socket:
                    attempt = 0
                    LOGGER.info("Connected to relay as %s", self.settings.device_id)
                    await self._run_connection(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = min(30.0, 1.5**attempt) + random.random()
                LOGGER.warning("Relay connection failed: %s; retrying in %.1fs", exc, delay)
                await asyncio.sleep(delay)

    async def _run_connection(self, socket: Any) -> None:
        send_lock = asyncio.Lock()

        async def send(event: Envelope) -> None:
            async with send_lock:
                await socket.send(event.model_dump_json())

        await send(
            Envelope(
                type="hello",
                deviceId=self.settings.device_id,
                payload={
                    "deviceId": self.settings.device_id,
                    "name": self.settings.device_name,
                    "os": platform.platform(),
                    "architecture": platform.machine(),
                    "capabilities": {
                        "telemetry": True,
                        "claudeCommands": self.settings.allow_claude_commands,
                        "providers": [provider.name for provider in self.providers],
                    },
                },
            )
        )

        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self._telemetry_loop(send))
            tasks.create_task(self._activity_loop(send))
            tasks.create_task(self._receive_loop(socket, send))

    async def _telemetry_loop(self, send: Any) -> None:
        while True:
            payload = await asyncio.to_thread(self.collector.sample)
            await send(Envelope(type="telemetry", deviceId=self.settings.device_id, payload=payload))
            await asyncio.sleep(self.settings.sample_interval)

    async def _activity_loop(self, send: Any) -> None:
        while True:
            states = await asyncio.gather(*(asyncio.to_thread(provider.state) for provider in self.providers))
            await send(
                Envelope(
                    type="provider_state",
                    deviceId=self.settings.device_id,
                    payload={state["name"]: state for state in states},
                )
            )
            for provider in self.providers:
                for event in await asyncio.to_thread(provider.poll_events):
                    await send(Envelope(type="activity", deviceId=self.settings.device_id, payload=event))
            await asyncio.sleep(max(self.settings.sample_interval, 2.0))

    async def _receive_loop(self, socket: Any, send: Any) -> None:
        async for raw in socket:
            event = Envelope.model_validate(json.loads(raw))
            if event.type != "command":
                continue
            command = CommandPayload.model_validate(event.payload)
            result = await self.command_runner.execute(command.command)
            result["requestId"] = command.requestId
            result["target"] = command.target
            await send(Envelope(type="command_result", deviceId=self.settings.device_id, payload=result))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = AgentSettings.from_env()
    if settings.token == "development-token":
        LOGGER.warning("AIWM_TOKEN is using the insecure development default")
    try:
        asyncio.run(DesktopAgent(settings).run_forever())
    except KeyboardInterrupt:
        LOGGER.info("Agent stopped")


if __name__ == "__main__":
    main()
