from __future__ import annotations

import asyncio
import os
import platform
import shutil
from pathlib import Path
from typing import Any

import psutil

from .base import ActivityProvider
from .log_tail import JsonlTail


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
        if log_glob is None:
            home = Path.home()
            log_glob = str(home / ".claude" / "projects" / "**" / "*.jsonl")
        self.tail = JsonlTail(log_glob)

    def state(self) -> dict[str, Any]:
        processes = _processes_matching(("claude",))
        latest = self.tail.latest_file()
        return {
            "name": self.name,
            "running": bool(processes),
            "processes": processes,
            "latestActivityFile": str(latest) if latest else None,
        }

    def poll_events(self) -> list[dict[str, Any]]:
        return [{"provider": self.name, **event} for event in self.tail.poll()]


class ClaudeCommandRunner:
    def __init__(self, enabled: bool, workdir: Path) -> None:
        self.enabled = enabled
        self.workdir = workdir

    async def execute(self, command: str) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "output": "Remote Claude commands are disabled on this device"}
        executable = shutil.which("claude")
        if executable is None:
            return {"ok": False, "output": "claude executable was not found in PATH"}
        if not self.workdir.is_dir():
            return {"ok": False, "output": f"Configured work directory does not exist: {self.workdir}"}
        args = [executable, "-p", command, "--output-format", "text"]
        if os.getenv("AIWM_CLAUDE_CONTINUE", "false").lower() in {"1", "true", "yes"}:
            args.append("--continue")
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.workdir,
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
        return {"ok": process.returncode == 0, "output": output, "exitCode": process.returncode}
