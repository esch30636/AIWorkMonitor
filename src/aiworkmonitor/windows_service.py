from __future__ import annotations

import asyncio
import ctypes
import logging
import os
from contextlib import suppress
from typing import Any

import uvicorn

from aiworkmonitor.agent import DesktopAgent
from aiworkmonitor.config import AgentSettings, RelaySettings
from aiworkmonitor.relay import create_app


LOGGER = logging.getLogger("aiworkmonitor.windows_service")
_MUTEX_HANDLE: Any = None


def acquire_background_mutex() -> bool:
    """Allow one self-hosted relay/agent process per Windows user session."""
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\AIWorkMonitorBackgroundService")
    if not handle:
        raise OSError("Unable to create the AIWorkMonitor background mutex")
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


async def run_local_service(settings: AgentSettings, port: int) -> None:
    """Host the relay and this computer's agent in one persistent process."""
    relay_settings = RelaySettings(token=settings.token, host="0.0.0.0", port=port)
    uvicorn_config = uvicorn.Config(
        create_app(relay_settings),
        host=relay_settings.host,
        port=relay_settings.port,
        log_level="info",
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    relay_task = asyncio.create_task(server.serve(), name="local-relay")

    while not server.started:
        if relay_task.done():
            await relay_task
            raise RuntimeError(f"Local relay could not listen on port {port}")
        await asyncio.sleep(0.1)

    LOGGER.info("Local relay listening on 0.0.0.0:%s", port)
    agent_task = asyncio.create_task(DesktopAgent(settings).run_forever(), name="local-agent")
    done, pending = await asyncio.wait(
        {relay_task, agent_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in pending:
        with suppress(asyncio.CancelledError):
            await task
    for task in done:
        exception = task.exception()
        if exception:
            raise exception
    raise RuntimeError("AIWorkMonitor background service stopped unexpectedly")
