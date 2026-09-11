from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Iterable
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status

from .config import RelaySettings
from .models import CommandPayload, Envelope, utc_now

LOGGER = logging.getLogger("aiworkmonitor.relay")


class ConnectionRegistry:
    def __init__(self) -> None:
        self.agents: dict[str, WebSocket] = {}
        self.mobiles: set[WebSocket] = set()
        self.devices: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect_agent(self, device_id: str, socket: WebSocket) -> None:
        async with self._lock:
            old_socket = self.agents.get(device_id)
            self.agents[device_id] = socket
            current = self.devices.setdefault(device_id, {"deviceId": device_id})
            current.update({"online": True, "lastSeen": utc_now()})
        if old_socket and old_socket is not socket:
            await old_socket.close(code=status.WS_1000_NORMAL_CLOSURE)

    async def disconnect_agent(self, device_id: str, socket: WebSocket) -> None:
        async with self._lock:
            if self.agents.get(device_id) is socket:
                self.agents.pop(device_id, None)
                current = self.devices.setdefault(device_id, {"deviceId": device_id})
                current.update({"online": False, "lastSeen": utc_now()})

    async def update_device(self, device_id: str, event_type: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            current = self.devices.setdefault(device_id, {"deviceId": device_id})
            current.update({"online": True, "lastSeen": utc_now()})
            if event_type == "hello":
                current.update(payload)
            elif event_type == "telemetry":
                current["telemetry"] = payload
            elif event_type == "activity":
                activity = current.setdefault("activity", [])
                activity.append(payload)
                current["activity"] = activity[-100:]
            elif event_type == "provider_state":
                current["providers"] = payload
            elif event_type == "command_result":
                results = current.setdefault("commandResults", [])
                results.append(payload)
                current["commandResults"] = results[-20:]

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            devices = [dict(value) for value in self.devices.values()]
        devices.sort(key=lambda value: str(value.get("name", value.get("deviceId", ""))))
        return {"devices": devices, "timestamp": utc_now()}

    async def broadcast_snapshot(self) -> None:
        message = Envelope(type="snapshot", payload=await self.snapshot()).model_dump(mode="json")
        await self._send_many(self.mobiles, message)

    async def add_mobile(self, socket: WebSocket) -> None:
        async with self._lock:
            self.mobiles.add(socket)

    async def remove_mobile(self, socket: WebSocket) -> None:
        async with self._lock:
            self.mobiles.discard(socket)

    async def send_command(self, device_id: str, command: CommandPayload) -> bool:
        async with self._lock:
            socket = self.agents.get(device_id)
        if socket is None:
            return False
        await socket.send_json(
            Envelope(type="command", deviceId=device_id, payload=command.model_dump()).model_dump(mode="json")
        )
        return True

    async def _send_many(self, sockets: Iterable[WebSocket], message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for socket in list(sockets):
            try:
                await socket.send_json(message)
            except Exception:
                stale.append(socket)
        if stale:
            async with self._lock:
                for socket in stale:
                    self.mobiles.discard(socket)


def create_app(settings: RelaySettings | None = None) -> FastAPI:
    config = settings or RelaySettings.from_env()
    registry = ConnectionRegistry()
    app = FastAPI(title="AIWorkMonitor Relay", version="0.2.0")
    app.state.settings = config
    app.state.registry = registry

    def token_valid(candidate: str | None) -> bool:
        return bool(candidate) and secrets.compare_digest(candidate, config.token)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        snapshot = await registry.snapshot()
        return {"status": "ok", "deviceCount": len(snapshot["devices"])}

    @app.get("/api/devices")
    async def devices(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        candidate = authorization.removeprefix("Bearer ") if authorization else None
        if not token_valid(candidate):
            raise HTTPException(status_code=401, detail="Invalid token")
        return await registry.snapshot()

    @app.websocket("/ws/agent/{device_id}")
    async def agent_socket(websocket: WebSocket, device_id: str) -> None:
        if not token_valid(websocket.query_params.get("token")):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        await registry.connect_agent(device_id, websocket)
        try:
            while True:
                raw = await websocket.receive_json()
                event = Envelope.model_validate(raw)
                if event.type not in {"hello", "telemetry", "activity", "provider_state", "command_result"}:
                    continue
                await registry.update_device(device_id, event.type, event.payload)
                await registry.broadcast_snapshot()
        except WebSocketDisconnect:
            pass
        finally:
            await registry.disconnect_agent(device_id, websocket)
            await registry.broadcast_snapshot()

    @app.websocket("/ws/mobile")
    async def mobile_socket(websocket: WebSocket) -> None:
        if not token_valid(websocket.query_params.get("token")):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        await registry.add_mobile(websocket)
        await websocket.send_json(
            Envelope(type="snapshot", payload=await registry.snapshot()).model_dump(mode="json")
        )
        try:
            while True:
                raw = await websocket.receive_json()
                event = Envelope.model_validate(raw)
                if event.type != "command" or not event.deviceId:
                    continue
                command = CommandPayload.model_validate(event.payload)
                delivered = await registry.send_command(event.deviceId, command)
                if not delivered:
                    await websocket.send_json(
                        Envelope(
                            type="command_result",
                            deviceId=event.deviceId,
                            payload={
                                "requestId": command.requestId,
                                "ok": False,
                                "output": "Device is offline",
                            },
                        ).model_dump(mode="json")
                    )
        except WebSocketDisconnect:
            pass
        finally:
            await registry.remove_mobile(websocket)

    return app


app = create_app()


def main() -> None:
    settings = RelaySettings.from_env()
    if settings.token == "development-token":
        LOGGER.warning("AIWM_TOKEN is using the insecure development default")
    uvicorn.run("aiworkmonitor.relay:app", host=settings.host, port=settings.port, reload=False)
