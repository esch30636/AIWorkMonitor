from fastapi.testclient import TestClient

from aiworkmonitor.config import RelaySettings
from aiworkmonitor.relay import create_app


def test_agent_mobile_snapshot_and_command_round_trip() -> None:
    app = create_app(RelaySettings(token="secret", host="127.0.0.1", port=8765))
    client = TestClient(app)

    with client.websocket_connect("/ws/agent/pc-1?token=secret") as agent:
        with client.websocket_connect("/ws/mobile?token=secret") as mobile:
            initial = mobile.receive_json()
            assert initial["type"] == "snapshot"

            agent.send_json({"type": "hello", "deviceId": "pc-1", "payload": {"name": "Main PC"}})
            snapshot = mobile.receive_json()
            assert snapshot["payload"]["devices"][0]["name"] == "Main PC"

            mobile.send_json(
                {
                    "type": "command",
                    "deviceId": "pc-1",
                    "payload": {"target": "claude-code", "command": "run tests", "requestId": "req-1"},
                }
            )
            forwarded = agent.receive_json()
            assert forwarded["type"] == "command"
            assert forwarded["payload"]["command"] == "run tests"

            agent.send_json(
                {
                    "type": "command_result",
                    "deviceId": "pc-1",
                    "payload": {"requestId": "req-1", "ok": True, "output": "done"},
                }
            )
            completed = mobile.receive_json()
            device = completed["payload"]["devices"][0]
            assert device["commandResults"][-1]["output"] == "done"

