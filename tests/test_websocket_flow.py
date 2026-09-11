from fastapi.testclient import TestClient
from pydantic import ValidationError

from aiworkmonitor.config import RelaySettings
from aiworkmonitor.models import CommandPayload
from aiworkmonitor.relay import create_app


def test_compact_command_allows_empty_focus_instructions() -> None:
    command = CommandPayload(
        target="claude-code",
        action="compact",
        command="",
        requestId="req-compact",
        sessionId="12345678-1234-1234-1234-123456789abc",
    )

    assert command.action == "compact"
    assert command.command == ""


def test_prompt_command_rejects_empty_text() -> None:
    try:
        CommandPayload(target="claude-code", action="prompt", command=" ", requestId="req-empty")
    except ValidationError:
        return
    raise AssertionError("An empty Claude prompt must be rejected")


def test_custom_gateway_model_id_is_allowed() -> None:
    command = CommandPayload(
        target="claude-code",
        command="check status",
        requestId="req-custom-model",
        model="deepseek-flash",
    )

    assert command.model == "deepseek-flash"


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
                    "payload": {
                        "target": "claude-code",
                        "action": "prompt",
                        "command": "run tests",
                        "requestId": "req-1",
                        "sessionId": "12345678-1234-1234-1234-123456789abc",
                        "model": "sonnet",
                        "effort": "high",
                    },
                }
            )
            forwarded = agent.receive_json()
            assert forwarded["type"] == "command"
            assert forwarded["payload"]["command"] == "run tests"
            assert forwarded["payload"]["sessionId"] == "12345678-1234-1234-1234-123456789abc"
            assert forwarded["payload"]["model"] == "sonnet"
            assert forwarded["payload"]["effort"] == "high"

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
