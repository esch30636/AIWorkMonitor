from __future__ import annotations

import asyncio
import glob
import json
import platform
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from .base import ActivityProvider
from .log_tail import JsonlTail


DEFAULT_ACTIVE_WINDOW_SECONDS = 30 * 60


def default_claude_log_glob() -> str:
    return str(Path.home() / ".claude" / "projects" / "**" / "*.jsonl")


@dataclass(frozen=True)
class ClaudeSession:
    sessionId: str
    projectName: str
    projectPath: str
    sourceFile: str
    lastActivityAt: str
    active: bool
    gitBranch: str | None = None
    slug: str | None = None


class ClaudeSessionLocator:
    def __init__(self, log_glob: str | None = None, active_window_seconds: int = DEFAULT_ACTIVE_WINDOW_SECONDS) -> None:
        self.log_glob = log_glob or default_claude_log_glob()
        self.active_window_seconds = active_window_seconds

    def latest_file(self) -> Path | None:
        candidates = [Path(value) for value in glob.glob(self.log_glob, recursive=True)]
        candidates = [value for value in candidates if value.is_file()]
        return max(candidates, key=lambda value: value.stat().st_mtime, default=None)

    def latest_session(self, *, claude_running: bool | None = None) -> ClaudeSession | None:
        path = self.latest_file()
        if path is None:
            return None
        metadata = self._recent_metadata(path)
        project_path = metadata.get("cwd")
        if not isinstance(project_path, str) or not project_path:
            return None
        session_id = metadata.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            session_id = path.stem
        modified = path.stat().st_mtime
        if claude_running is None:
            claude_running = bool(_processes_matching(("claude",)))
        return ClaudeSession(
            sessionId=session_id,
            projectName=Path(project_path).name or project_path,
            projectPath=project_path,
            sourceFile=str(path),
            lastActivityAt=datetime.fromtimestamp(modified, UTC).isoformat(),
            active=bool(claude_running) and time.time() - modified <= self.active_window_seconds,
            gitBranch=metadata.get("gitBranch") if isinstance(metadata.get("gitBranch"), str) else None,
            slug=metadata.get("slug") if isinstance(metadata.get("slug"), str) else None,
        )

    @staticmethod
    def _recent_metadata(path: Path, max_bytes: int = 512 * 1024) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                size = path.stat().st_size
                start = max(0, size - max_bytes)
                handle.seek(start)
                raw = handle.read()
        except OSError:
            return {}
        lines = raw.decode("utf-8", errors="replace").splitlines()
        if start > 0 and lines:
            lines = lines[1:]
        metadata: dict[str, Any] = {}
        wanted = {"cwd", "sessionId", "gitBranch", "slug"}
        for line in reversed(lines[-500:]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict):
                continue
            for key in wanted - metadata.keys():
                candidate = value.get(key)
                if candidate is not None and candidate != "":
                    metadata[key] = candidate
            if "cwd" in metadata and "sessionId" in metadata:
                break
        return metadata


def _processes_matching(needles: tuple[str, ...]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            process_name = str(process.info.get("name") or "").lower().removesuffix(".exe")
            command_parts = [str(part).lower() for part in (process.info.get("cmdline") or [])[:4]]
            command_names = [Path(part.strip('"')).name.removesuffix(".exe") for part in command_parts]
            direct_match = any(needle == process_name or needle in command_names for needle in needles)
            claude_node_match = "claude" in needles and any("claude-code" in part for part in command_parts)
            if direct_match or claude_node_match:
                matches.append({"pid": process.pid, "name": process.info.get("name") or "unknown"})
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches[:20]


class ClaudeCodeProvider(ActivityProvider):
    name = "claude-code"

    def __init__(self, log_glob: str | None = None) -> None:
        log_glob = log_glob or default_claude_log_glob()
        self.tail = JsonlTail(log_glob)
        self.locator = ClaudeSessionLocator(log_glob)

    def state(self) -> dict[str, Any]:
        processes = _processes_matching(("claude",))
        session = self.locator.latest_session(claude_running=bool(processes))
        return {
            "name": self.name,
            "running": bool(processes),
            "processes": processes,
            "mode": "active-session" if session and session.active else "process-only" if processes else "offline",
            "activeSession": asdict(session) if session else None,
        }

    def poll_events(self) -> list[dict[str, Any]]:
        session = self.locator.latest_session()
        session_context = (
            {
                "sessionId": session.sessionId,
                "projectName": session.projectName,
                "projectPath": session.projectPath,
            }
            if session
            else {}
        )
        return [{"provider": self.name, **session_context, **event} for event in self.tail.poll()]


class ClaudeCommandRunner:
    def __init__(self, enabled: bool, log_glob: str | None = None) -> None:
        self.enabled = enabled
        self.locator = ClaudeSessionLocator(log_glob)

    async def execute(self, command: str) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "output": "Remote Claude commands are disabled on this device"}
        executable = shutil.which("claude")
        if executable is None:
            return {"ok": False, "output": "claude executable was not found in PATH"}
        session = self.locator.latest_session()
        if session is None:
            return {"ok": False, "output": "No Claude Code session could be detected on this computer"}
        workdir = Path(session.projectPath)
        if not workdir.is_dir():
            return {"ok": False, "output": f"The active Claude project no longer exists: {workdir}"}
        args = [executable, "-p", command, "--output-format", "text"]
        args.extend(["--resume", session.sessionId])
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=creationflags,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=900)
        except TimeoutError:
            process.kill()
            await process.wait()
            return {"ok": False, "output": "Claude command timed out after 15 minutes"}
        except OSError as exc:
            return {"ok": False, "output": str(exc)}
        output = stdout.decode(errors="replace")[-20_000:]
        return {
            "ok": process.returncode == 0,
            "output": output,
            "exitCode": process.returncode,
            "sessionId": session.sessionId,
            "projectName": session.projectName,
            "projectPath": session.projectPath,
        }
