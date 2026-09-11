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


def test_claude_session_locator_lists_recent_sessions_for_mobile_picker(tmp_path) -> None:
    first_project = tmp_path / "first-project"
    second_project = tmp_path / "second-project"
    first_project.mkdir()
    second_project.mkdir()
    first_id = "11111111-1111-1111-1111-111111111111"
    second_id = "22222222-2222-2222-2222-222222222222"
    first_log = tmp_path / f"{first_id}.jsonl"
    second_log = tmp_path / f"{second_id}.jsonl"
    _write_session(first_log, first_project, first_id)
    _write_session(second_log, second_project, second_id)
    first_log.touch()

    locator = ClaudeSessionLocator(str(tmp_path / "*.jsonl"))
    sessions = locator.sessions(20, claude_running=True)

    assert [session.sessionId for session in sessions] == [first_id, second_id]
    assert locator.session_by_id(second_id).projectName == "second-project"


def test_locator_matches_each_running_process_to_its_project_session(tmp_path, monkeypatch) -> None:
    first_root = tmp_path / "HUSTRunner"
    second_root = tmp_path / "CUMCM"
    first_working = first_root / "src"
    second_working = second_root / "cumcm2026" / "A" / "02-lit"
    first_working.mkdir(parents=True)
    second_working.mkdir(parents=True)
    first_id = "11111111-1111-1111-1111-111111111111"
    second_id = "22222222-2222-2222-2222-222222222222"
    old_id = "33333333-3333-3333-3333-333333333333"
    first_bucket = tmp_path / "projects" / claude._claude_project_key(first_root)
    second_bucket = tmp_path / "projects" / claude._claude_project_key(second_root)
    first_bucket.mkdir(parents=True)
    second_bucket.mkdir(parents=True)
    _write_session(first_bucket / f"{first_id}.jsonl", first_working, first_id)
    _write_session(second_bucket / f"{old_id}.jsonl", second_root, old_id)
    _write_session(second_bucket / f"{second_id}.jsonl", second_working, second_id)
    (second_bucket / f"{second_id}.jsonl").touch()
    monkeypatch.setattr(
        claude,
        "_processes_matching",
        lambda needles: [
            {"pid": 10, "name": "claude", "cwd": str(first_root)},
            {"pid": 20, "name": "claude", "cwd": str(second_root)},
        ],
    )

    locator = ClaudeSessionLocator(str(tmp_path / "projects" / "**" / "*.jsonl"))
    sessions = locator.sessions()
    active = [session for session in sessions if session.active]

    assert {session.sessionId for session in active} == {first_id, second_id}
    assert {session.projectName for session in active} == {"HUSTRunner", "CUMCM"}
    second = next(session for session in active if session.sessionId == second_id)
    assert second.projectPath == str(second_root)
    assert second.workingDirectory == str(second_working)
    assert second.processId == 20
    assert not next(session for session in sessions if session.sessionId == old_id).active


def test_provider_publishes_all_active_sessions(tmp_path, monkeypatch) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    session_ids = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
    for root, session_id in zip(roots, session_ids, strict=True):
        root.mkdir()
        bucket = tmp_path / "projects" / claude._claude_project_key(root)
        bucket.mkdir(parents=True)
        _write_session(bucket / f"{session_id}.jsonl", root, session_id)
    monkeypatch.setattr(
        claude,
        "_processes_matching",
        lambda needles: [
            {"pid": index, "name": "claude", "cwd": str(root)} for index, root in enumerate(roots, 1)
        ],
    )

    state = ClaudeCodeProvider(str(tmp_path / "projects" / "**" / "*.jsonl")).state()

    assert len(state["activeSessions"]) == 2
    assert {session["projectName"] for session in state["activeSessions"]} == {"first", "second"}


def test_runtime_registry_selects_exact_resumed_session_and_title(tmp_path, monkeypatch) -> None:
    project = tmp_path / "CUMCM"
    project.mkdir()
    bucket = tmp_path / "projects" / claude._claude_project_key(project)
    bucket.mkdir(parents=True)
    older_id = "11111111-1111-1111-1111-111111111111"
    newer_id = "22222222-2222-2222-2222-222222222222"
    older_log = bucket / f"{older_id}.jsonl"
    newer_log = bucket / f"{newer_id}.jsonl"
    _write_session(older_log, project, older_id)
    _write_session(newer_log, project, newer_id)
    newer_log.touch()
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "77.json").write_text(
        json.dumps(
            {
                "pid": 77,
                "sessionId": older_id,
                "cwd": str(project),
                "name": "目录文件选题",
                "status": "idle",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claude,
        "_processes_matching",
        lambda needles: [{"pid": 77, "name": "claude", "cwd": str(project)}],
    )

    sessions = ClaudeSessionLocator(
        str(tmp_path / "projects" / "**" / "*.jsonl"),
        sessions_dir=sessions_dir,
        history_path=tmp_path / "missing-history.jsonl",
    ).sessions()

    active = next(session for session in sessions if session.active)
    assert active.sessionId == older_id
    assert active.displayName == "目录文件选题"
    assert active.status == "idle"
    assert not next(session for session in sessions if session.sessionId == newer_id).active


def test_history_supplies_project_root_and_latest_prompt(tmp_path) -> None:
    project = tmp_path / "HUSTRunner"
    working = project / "nested"
    working.mkdir(parents=True)
    session_id = "12345678-1234-1234-1234-123456789abc"
    log = tmp_path / f"{session_id}.jsonl"
    _write_session(log, working, session_id)
    history = tmp_path / "history.jsonl"
    history.write_text(
        json.dumps(
            {
                "display": "检查最新测试结果",
                "project": str(project),
                "sessionId": session_id,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    session = ClaudeSessionLocator(
        str(tmp_path / "*.jsonl"),
        sessions_dir=tmp_path / "sessions",
        history_path=history,
    ).latest_session(claude_running=False)

    assert session is not None
    assert session.projectPath == str(project)
    assert session.workingDirectory == str(working)
    assert session.lastPrompt == "检查最新测试结果"


def test_process_match_does_not_treat_arbitrary_command_text_as_claude() -> None:
    assert not claude._process_command_matches(
        "powershell",
        ["powershell.exe", "-command", "print provider_state['claude-code']"],
        ("claude",),
    )
    assert claude._process_command_matches(
        "node",
        ["node.exe", r"C:\npm\node_modules\@anthropic-ai\claude-code\cli.js"],
        ("claude",),
    )


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


def test_claude_command_runner_uses_selected_session_model_and_effort(tmp_path, monkeypatch) -> None:
    first_project = tmp_path / "first-project"
    selected_project = tmp_path / "selected-project"
    first_project.mkdir()
    selected_project.mkdir()
    first_id = "11111111-1111-1111-1111-111111111111"
    selected_id = "22222222-2222-2222-2222-222222222222"
    _write_session(tmp_path / f"{first_id}.jsonl", first_project, first_id)
    _write_session(tmp_path / f"{selected_id}.jsonl", selected_project, selected_id)
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"compacted", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(claude.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(claude.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = ClaudeCommandRunner(True, str(tmp_path / "*.jsonl"))

    result = asyncio.run(
        runner.execute(
            "保留测试结果",
            action="compact",
            session_id=selected_id,
            model="opus",
            effort="xhigh",
        )
    )

    assert result["ok"]
    assert result["action"] == "compact"
    assert result["sessionId"] == selected_id
    assert captured["cwd"] == selected_project
    assert captured["args"] == (
        "claude",
        "-p",
        "/compact 保留测试结果",
        "--output-format",
        "text",
        "--resume",
        selected_id,
        "--model",
        "opus",
        "--effort",
        "xhigh",
    )


def test_command_runner_resumes_from_project_root_not_last_nested_working_directory(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project-root"
    working_directory = project_root / "nested" / "work"
    working_directory.mkdir(parents=True)
    session_id = "12345678-1234-1234-1234-123456789abc"
    bucket = tmp_path / "projects" / claude._claude_project_key(project_root)
    bucket.mkdir(parents=True)
    _write_session(bucket / f"{session_id}.jsonl", working_directory, session_id)
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"done", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["cwd"] = kwargs["cwd"]
        return FakeProcess()

    monkeypatch.setattr(claude.shutil, "which", lambda name: "claude")
    monkeypatch.setattr(
        claude,
        "_processes_matching",
        lambda needles: [{"pid": 42, "name": "claude", "cwd": str(project_root)}],
    )
    monkeypatch.setattr(claude.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner = ClaudeCommandRunner(True, str(tmp_path / "projects" / "**" / "*.jsonl"))

    result = asyncio.run(runner.execute("check status", session_id=session_id))

    assert result["ok"]
    assert captured["cwd"] == project_root
