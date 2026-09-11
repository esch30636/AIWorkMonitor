import asyncio
import json
from pathlib import Path

from aiworkmonitor.providers import claude
from aiworkmonitor.providers.claude import ClaudeCodeProvider, ClaudeCommandRunner, ClaudeSessionLocator


def _write_session(log: Path, project: Path, session_id: str) -> None:
    log.write_text(
        json.dumps(
            {
                "type": "user",
                "cwd": str(project),
                "sessionId": session_id,
                "gitBranch": "main",
                "message": {"role": "user", "content": "existing"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_claude_session_locator_discovers_latest_project(tmp_path) -> None:
    project = tmp_path / "active-project"
    project.mkdir()
    session_id = "12345678-1234-1234-1234-123456789abc"
    log = tmp_path / f"{session_id}.jsonl"
    _write_session(log, project, session_id)

    session = ClaudeSessionLocator(str(tmp_path / "*.jsonl")).latest_session(claude_running=True)

    assert session is not None
    assert session.sessionId == session_id
    assert session.projectName == "active-project"
    assert session.projectPath == str(project)
    assert session.active


def test_claude_provider_attaches_active_project_to_new_events(tmp_path, monkeypatch) -> None:
    project = tmp_path / "live-project"
    project.mkdir()
    session_id = "12345678-1234-1234-1234-123456789abc"
    log = tmp_path / f"{session_id}.jsonl"
    _write_session(log, project, session_id)
    monkeypatch.setattr(claude, "_processes_matching", lambda needles: [{"pid": 1, "name": "claude"}])
    provider = ClaudeCodeProvider(str(tmp_path / "*.jsonl"))
    assert provider.poll_events() == []

    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "cwd": str(project),
                    "sessionId": session_id,
                    "message": {"role": "assistant", "content": "working"},
                }
            )
            + "\n"
        )

    events = provider.poll_events()
    assert events[0]["projectName"] == "live-project"
    assert events[0]["sessionId"] == session_id
    assert events[0]["text"] == "working"
    assert provider.state()["activeSession"]["projectName"] == "live-project"


def test_claude_command_runner_resumes_discovered_session(tmp_path, monkeypatch) -> None:
    project = tmp_path / "command-project"
    project.mkdir()
    session_id = "12345678-1234-1234-1234-123456789abc"
    _write_session(tmp_path / f"{session_id}.jsonl", project, session_id)
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"done", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(claude.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(claude.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = ClaudeCommandRunner(True, str(tmp_path / "*.jsonl"))

    result = asyncio.run(runner.execute("check status"))

    assert result["ok"]
    assert result["projectName"] == "command-project"
    assert captured["cwd"] == project
    assert captured["args"][-2:] == ("--resume", session_id)
