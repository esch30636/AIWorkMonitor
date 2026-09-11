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
from .log_tail import JsonlTail, decode_log_line


DEFAULT_ACTIVE_WINDOW_SECONDS = 30 * 60
CLAUDE_MODELS = (
    "session",
    "default",
    "best",
    "fable",
    "sonnet",
    "opus",
    "haiku",
    "sonnet[1m]",
    "opus[1m]",
    "opusplan",
)
CLAUDE_EFFORT_LEVELS = ("auto", "low", "medium", "high", "xhigh", "max", "ultracode")


def default_claude_log_glob() -> str:
    return str(Path.home() / ".claude" / "projects" / "**" / "*.jsonl")


def default_claude_sessions_dir() -> Path:
    return Path.home() / ".claude" / "sessions"


def default_claude_history_path() -> Path:
    return Path.home() / ".claude" / "history.jsonl"


@dataclass(frozen=True)
class ClaudeSession:
    sessionId: str
    projectName: str
    projectPath: str
    workingDirectory: str
    sourceFile: str
    lastActivityAt: str
    active: bool
    gitBranch: str | None = None
    slug: str | None = None
    displayName: str | None = None
    model: str | None = None
    lastPrompt: str | None = None
    processId: int | None = None
    status: str | None = None


class ClaudeSessionLocator:
    def __init__(
        self,
        log_glob: str | None = None,
        active_window_seconds: int = DEFAULT_ACTIVE_WINDOW_SECONDS,
        sessions_dir: Path | None = None,
        history_path: Path | None = None,
    ) -> None:
        self.log_glob = log_glob or default_claude_log_glob()
        self.active_window_seconds = active_window_seconds
        self.sessions_dir = sessions_dir or default_claude_sessions_dir()
        self.history_path = history_path or default_claude_history_path()
        self._metadata_cache: dict[Path, tuple[int, int, dict[str, Any]]] = {}
        self._history_cache: tuple[int, int, dict[str, dict[str, Any]]] | None = None

    def latest_file(self) -> Path | None:
        candidates = [Path(value) for value in glob.glob(self.log_glob, recursive=True)]
        candidates = [value for value in candidates if value.is_file()]
        return max(candidates, key=lambda value: value.stat().st_mtime, default=None)

    def latest_session(
        self,
        *,
        claude_running: bool | None = None,
        processes: list[dict[str, Any]] | None = None,
    ) -> ClaudeSession | None:
        sessions = self.sessions(100, claude_running=claude_running, processes=processes)
        return next((session for session in sessions if session.active), sessions[0] if sessions else None)

    def sessions(
        self,
        limit: int = 50,
        *,
        claude_running: bool | None = None,
        processes: list[dict[str, Any]] | None = None,
    ) -> list[ClaudeSession]:
        candidates = [Path(value) for value in glob.glob(self.log_glob, recursive=True)]
        candidates = [value for value in candidates if value.is_file()]
        candidates.sort(key=lambda value: value.stat().st_mtime, reverse=True)
        if processes is None:
            processes = _processes_matching(("claude",)) if claude_running is None else []
        if claude_running is None:
            claude_running = bool(processes)

        process_roots: list[tuple[Path, int]] = []
        for process in processes:
            cwd = process.get("cwd")
            if isinstance(cwd, str) and cwd:
                process_roots.append((Path(cwd), int(process["pid"])))

        history = self._history_by_session()
        metadata_by_path: dict[Path, dict[str, Any]] = {}
        for path in candidates:
            metadata = dict(self._metadata(path))
            session_id = metadata.get("sessionId") if isinstance(metadata.get("sessionId"), str) else path.stem
            history_item = history.get(session_id)
            if history_item:
                metadata["historyProject"] = history_item.get("project")
                metadata["historyPrompt"] = history_item.get("display")
            metadata_by_path[path] = metadata
        matches_by_root: dict[tuple[str, int], list[Path]] = {}
        root_for_path: dict[Path, tuple[Path, int]] = {}
        runtime_for_path: dict[Path, dict[str, Any]] = {}
        exact_active_paths: set[Path] = set()
        for root, pid in process_roots:
            root_key = _claude_project_key(root)
            matches = [
                path
                for path in candidates
                if path.parent.name.casefold() == root_key.casefold()
                or _is_within(metadata_by_path[path].get("cwd"), root)
            ]
            if matches:
                matches_by_root[(str(root), pid)] = matches
                for path in matches:
                    root_for_path[path] = (root, pid)

            runtime = self._runtime_session(pid)
            if runtime:
                runtime_session_id = runtime.get("sessionId")
                exact_path = next((path for path in candidates if path.stem == runtime_session_id), None)
                runtime_root = runtime.get("cwd")
                if exact_path is not None:
                    exact_active_paths.add(exact_path)
                    runtime_for_path[exact_path] = runtime
                    root_for_path[exact_path] = (
                        Path(runtime_root) if isinstance(runtime_root, str) and runtime_root else root,
                        pid,
                    )

        active_paths = set(exact_active_paths)
        for (_, pid), matches in matches_by_root.items():
            if matches and not any(path in exact_active_paths and root_for_path[path][1] == pid for path in matches):
                active_paths.add(matches[0])
        sessions: list[ClaudeSession] = []
        seen: set[str] = set()
        for path in candidates:
            matched = root_for_path.get(path)
            runtime = runtime_for_path.get(path)
            if runtime:
                metadata_by_path[path]["runtimeName"] = runtime.get("name")
                metadata_by_path[path]["runtimeStatus"] = runtime.get("status")
            session = self._session_from_path(
                path,
                metadata=metadata_by_path[path],
                project_root=matched[0] if matched else None,
                process_id=matched[1] if matched and path in active_paths else None,
                active=path in active_paths,
                claude_running=claude_running if not process_roots else False,
            )
            if session is None or session.sessionId in seen:
                continue
            sessions.append(session)
            seen.add(session.sessionId)
            if len(sessions) >= limit:
                break
        return sorted(sessions, key=lambda session: not session.active)

    def session_by_id(self, session_id: str) -> ClaudeSession | None:
        for session in self.sessions(limit=500):
            if session.sessionId == session_id:
                return session
        return None

    def _session_from_path(
        self,
        path: Path,
        *,
        metadata: dict[str, Any] | None = None,
        project_root: Path | None = None,
        process_id: int | None = None,
        active: bool = False,
        claude_running: bool | None = None,
    ) -> ClaudeSession | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        metadata = metadata or self._metadata(path)
        project_path = metadata.get("cwd")
        if not isinstance(project_path, str) or not project_path:
            return None
        session_id = metadata.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            session_id = path.stem
        modified = stat.st_mtime
        root_path = project_root or Path(
            str(metadata.get("historyProject") or metadata.get("initialCwd") or project_path)
        )
        if claude_running is None:
            claude_running = bool(_processes_matching(("claude",)))
        inferred_active = bool(claude_running) and time.time() - modified <= self.active_window_seconds
        display_name = _first_text(metadata, "runtimeName", "customTitle", "aiTitle", "agentName", "slug")
        return ClaudeSession(
            sessionId=session_id,
            projectName=root_path.name or str(root_path),
            projectPath=str(root_path),
            workingDirectory=project_path,
            sourceFile=str(path),
            lastActivityAt=datetime.fromtimestamp(modified, UTC).isoformat(),
            active=active or inferred_active,
            gitBranch=metadata.get("gitBranch") if isinstance(metadata.get("gitBranch"), str) else None,
            slug=metadata.get("slug") if isinstance(metadata.get("slug"), str) else None,
            displayName=display_name,
            model=metadata.get("model") if isinstance(metadata.get("model"), str) else None,
            lastPrompt=_first_text(metadata, "historyPrompt", "lastPrompt"),
            processId=process_id,
            status=_first_text(metadata, "runtimeStatus"),
        )

    def _metadata(self, path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
        except OSError:
            return {}
        cached = self._metadata_cache.get(path)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]
        metadata = self._recent_metadata(path)
        metadata.update({key: value for key, value in self._initial_metadata(path).items() if key not in metadata})
        self._metadata_cache[path] = (stat.st_mtime_ns, stat.st_size, metadata)
        return metadata

    def _runtime_session(self, pid: int) -> dict[str, Any] | None:
        path = self.sessions_dir / f"{pid}.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("pid") != pid:
            return None
        if not isinstance(value.get("sessionId"), str) or not value["sessionId"]:
            return None
        return value

    def _history_by_session(self) -> dict[str, dict[str, Any]]:
        try:
            stat = self.history_path.stat()
        except OSError:
            return {}
        if self._history_cache and self._history_cache[0] == stat.st_mtime_ns and self._history_cache[1] == stat.st_size:
            return self._history_cache[2]
        result: dict[str, dict[str, Any]] = {}
        try:
            lines = self.history_path.read_bytes().splitlines()
        except OSError:
            return {}
        for line in lines:
            try:
                value = json.loads(decode_log_line(line))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            session_id = value.get("sessionId")
            if isinstance(session_id, str) and session_id:
                result[session_id] = value
        self._history_cache = (stat.st_mtime_ns, stat.st_size, result)
        return result

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
        lines = raw.splitlines()
        if start > 0 and lines:
            lines = lines[1:]
        metadata: dict[str, Any] = {}
        wanted = {
            "cwd",
            "sessionId",
            "gitBranch",
            "slug",
            "customTitle",
            "aiTitle",
            "agentName",
            "lastPrompt",
            "model",
        }
        for line in reversed(lines[-500:]):
            try:
                value = json.loads(decode_log_line(line))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            for key in wanted - metadata.keys():
                candidate = value.get(key)
                if candidate is not None and candidate != "":
                    metadata[key] = candidate
            message = value.get("message")
            if "model" not in metadata and isinstance(message, dict):
                candidate_model = message.get("model")
                if isinstance(candidate_model, str) and candidate_model:
                    metadata["model"] = candidate_model
        return metadata

    @staticmethod
    def _initial_metadata(path: Path, max_bytes: int = 256 * 1024) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                raw = handle.read(max_bytes)
        except OSError:
            return {}
        for line in raw.splitlines():
            try:
                value = json.loads(decode_log_line(line))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and isinstance(value.get("cwd"), str) and value["cwd"]:
                return {"initialCwd": value["cwd"]}
        return {}


def _claude_project_key(path: Path) -> str:
    return str(path).replace(":", "-").replace("\\", "-").replace("/", "-")


def _is_within(candidate: Any, root: Path) -> bool:
    if not isinstance(candidate, str) or not candidate:
        return False
    try:
        Path(candidate).resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _first_text(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and _text_is_usable(value):
            return value.strip()[:240]
    return None


def _text_is_usable(value: str) -> bool:
    text = value.strip()
    return bool(text) and text.lower() != "null" and "\ufffd" not in text


def _processes_matching(needles: tuple[str, ...]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            process_name = str(process.info.get("name") or "").lower().removesuffix(".exe")
            command_parts = [str(part).lower() for part in (process.info.get("cmdline") or [])[:4]]
            if _process_command_matches(process_name, command_parts, needles):
                try:
                    cwd = process.cwd()
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                    cwd = None
                matches.append({"pid": process.pid, "name": process.info.get("name") or "unknown", "cwd": cwd})
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return matches[:20]


def _process_command_matches(process_name: str, command_parts: list[str], needles: tuple[str, ...]) -> bool:
    command_names = [Path(part.strip('"')).name.removesuffix(".exe") for part in command_parts]
    direct_match = any(needle == process_name or needle in command_names for needle in needles)
    node_runtimes = {"node", "nodejs", "bun", "deno"}
    claude_node_match = (
        "claude" in needles
        and process_name in node_runtimes
        and any("claude-code" in part for part in command_parts)
    )
    return direct_match or claude_node_match


class ClaudeCodeProvider(ActivityProvider):
    name = "claude-code"

    def __init__(self, log_glob: str | None = None) -> None:
        log_glob = log_glob or default_claude_log_glob()
        self.tail = JsonlTail(log_glob)
        self.locator = ClaudeSessionLocator(log_glob)

    def state(self) -> dict[str, Any]:
        processes = _processes_matching(("claude",))
        sessions = self.locator.sessions(50, processes=processes)
        active_sessions = [value for value in sessions if value.active]
        session = active_sessions[0] if active_sessions else (sessions[0] if sessions else None)
        return {
            "name": self.name,
            "running": bool(processes),
            "processes": processes,
            "mode": "active-session" if session and session.active else "process-only" if processes else "offline",
            "activeSession": asdict(session) if session else None,
            "activeSessions": [asdict(value) for value in active_sessions],
            "sessions": [asdict(value) for value in sessions],
            "controls": {
                "models": list(CLAUDE_MODELS),
                "efforts": list(CLAUDE_EFFORT_LEVELS),
                "actions": ["prompt", "compact"],
            },
        }

    def poll_events(self) -> list[dict[str, Any]]:
        sessions = self.locator.sessions(50)
        active_sessions = [session for session in sessions if session.active]
        watched = active_sessions or sessions[:1]
        by_source = {str(Path(session.sourceFile)): session for session in watched}
        events: list[dict[str, Any]] = []
        for event in self.tail.poll_paths([Path(session.sourceFile) for session in watched]):
            session = by_source.get(str(Path(event.get("sourceFile", ""))))
            context = (
                {
                    "sessionId": session.sessionId,
                    "projectName": session.projectName,
                    "projectPath": session.projectPath,
                }
                if session
                else {}
            )
            events.append({"provider": self.name, **context, **event})
        return events


class ClaudeCommandRunner:
    def __init__(self, enabled: bool, log_glob: str | None = None) -> None:
        self.enabled = enabled
        self.locator = ClaudeSessionLocator(log_glob)

    async def execute(
        self,
        command: str,
        *,
        action: str = "prompt",
        session_id: str | None = None,
        model: str = "session",
        effort: str = "auto",
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "output": "Remote Claude commands are disabled on this device"}
        executable = shutil.which("claude")
        if executable is None:
            return {"ok": False, "output": "claude executable was not found in PATH"}
        model = model.strip()
        if not model or len(model) > 256 or any(ord(character) < 32 or ord(character) == 127 for character in model):
            return {"ok": False, "output": "The Claude model ID is invalid"}
        if effort not in CLAUDE_EFFORT_LEVELS:
            return {"ok": False, "output": f"Unsupported Claude effort level: {effort}"}
        if action not in {"prompt", "compact"}:
            return {"ok": False, "output": f"Unsupported Claude action: {action}"}
        session = self.locator.session_by_id(session_id) if session_id else self.locator.latest_session()
        if session is None:
            message = (
                "The selected Claude Code session is no longer available on this computer"
                if session_id
                else "No Claude Code session could be detected on this computer"
            )
            return {"ok": False, "output": message}
        workdir = Path(session.projectPath)
        if not workdir.is_dir():
            return {"ok": False, "output": f"The active Claude project no longer exists: {workdir}"}
        prompt = command if action == "prompt" else f"/compact {command}".rstrip()
        args = [executable, "-p", prompt, "--output-format", "text"]
        args.extend(["--resume", session.sessionId])
        if model != "session":
            args.extend(["--model", model])
        if effort != "auto":
            args.extend(["--effort", effort])
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
            "action": action,
            "model": model,
            "effort": effort,
        }
