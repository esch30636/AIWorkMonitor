from __future__ import annotations

import base64
import ipaddress
import os
import secrets
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path


CONFIG_FILENAME = "aiworkmonitor.env"
EXECUTABLE_NAME = "AIWorkMonitorAgent.exe"
STARTUP_VALUE_NAME = "AIWorkMonitorAgent"
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DEFAULT_RELAY_PORT = 8765


def executable_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_install_directory() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Programs" / "AIWorkMonitor"
    return Path.home() / "AIWorkMonitor"


def automatic_device_identity() -> tuple[str, str]:
    hostname = socket.gethostname()
    return f"windows-{hostname}", hostname


def ensure_agent_config(
    path: Path,
    *,
    token_factory: Callable[[], str] | None = None,
) -> dict[str, str]:
    """Create or repair the permanent local identity without rotating its token."""
    values = read_config_values(path)
    token = values.get("AIWM_TOKEN", "")
    if not token or token == "development-token":
        token = (token_factory or (lambda: secrets.token_urlsafe(32)))()

    device_id, device_name = automatic_device_identity()
    desired: dict[str, str | bool | float] = {
        **values,
        "AIWM_TOKEN": token,
        "AIWM_RELAY_URL": f"ws://127.0.0.1:{values.get('AIWM_PORT', DEFAULT_RELAY_PORT)}",
        "AIWM_PORT": values.get("AIWM_PORT", str(DEFAULT_RELAY_PORT)),
        "AIWM_DEVICE_ID": device_id,
        "AIWM_DEVICE_NAME": device_name,
        "AIWM_SAMPLE_INTERVAL": values.get("AIWM_SAMPLE_INTERVAL", "2"),
        "AIWM_ALLOW_CLAUDE_COMMANDS": values.get("AIWM_ALLOW_CLAUDE_COMMANDS", "true"),
    }
    desired.pop("AIWM_CLAUDE_WORKDIR", None)
    comparable = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in desired.items()}
    if not path.is_file() or values != comparable:
        write_agent_config(path, desired)
    return read_config_values(path, required=True)


def preferred_mobile_host() -> str:
    """Prefer the machine's Tailscale IPv4, then a non-loopback LAN IPv4."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=creation_flags,
        )
        for line in result.stdout.splitlines():
            candidate = line.strip()
            address = ipaddress.ip_address(candidate)
            if isinstance(address, ipaddress.IPv4Address) and not address.is_loopback:
                return candidate
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    try:
        addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        for address_info in addresses:
            candidate = address_info[4][0]
            address = ipaddress.ip_address(candidate)
            if not address.is_loopback and not address.is_link_local:
                return candidate
    except (OSError, ValueError):
        pass
    return "127.0.0.1"


def mobile_websocket_url(port: int = DEFAULT_RELAY_PORT) -> str:
    return f"ws://{preferred_mobile_host()}:{port}"


def _protect_secret(value: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import win32crypt

        encrypted = win32crypt.CryptProtectData(
            value.encode("utf-8"),
            "AIWorkMonitor token",
            None,
            None,
            None,
            0,
        )
        return base64.b64encode(encrypted).decode("ascii")
    except Exception:
        return None


def _unprotect_secret(value: str) -> str:
    if os.name != "nt":
        raise ValueError("DPAPI-protected configuration can only be read on Windows")
    try:
        import win32crypt

        encrypted = base64.b64decode(value, validate=True)
        _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
        return decrypted.decode("utf-8")
    except Exception as exc:
        raise ValueError("Unable to decrypt the saved access token for this Windows account") from exc


def read_config_values(path: Path, *, required: bool = False) -> dict[str, str]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"Config file does not exist: {path}")
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key.startswith("AIWM_"):
            raise ValueError(f"Invalid config line {line_number}: unsupported key {key!r}")
        if key == "AIWM_TOKEN_DPAPI":
            values["AIWM_TOKEN"] = _unprotect_secret(value)
        else:
            values[key] = value

    return values


def load_config_file(path: Path, *, required: bool = False) -> bool:
    values = read_config_values(path, required=required)
    if not values and not path.is_file():
        return False
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return True


def write_agent_config(path: Path, values: Mapping[str, str | bool | float]) -> None:
    token = str(values.get("AIWM_TOKEN", ""))
    protected_token = _protect_secret(token) if token else None
    lines = [
        "# Generated by AIWorkMonitor Windows GUI.",
        "# The access token is protected with Windows DPAPI when available.",
    ]
    if protected_token:
        lines.append(f"AIWM_TOKEN_DPAPI={protected_token}")
    else:
        lines.append(f"AIWM_TOKEN={token}")

    ordered_keys = (
        "AIWM_RELAY_URL",
        "AIWM_PORT",
        "AIWM_DEVICE_ID",
        "AIWM_DEVICE_NAME",
        "AIWM_SAMPLE_INTERVAL",
        "AIWM_ALLOW_CLAUDE_COMMANDS",
        "AIWM_CLAUDE_LOG_GLOB",
        "AIWM_CHATGPT_LOG_GLOB",
    )
    for key in ordered_keys:
        if key not in values:
            continue
        raw_value = values[key]
        if isinstance(raw_value, bool):
            value = "true" if raw_value else "false"
        else:
            value = str(raw_value)
        if "\n" in value or "\r" in value:
            raise ValueError(f"Configuration value {key} cannot contain a new line")
        lines.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def startup_command(executable: Path) -> str:
    return f'"{executable.resolve()}" --background'


def startup_executable(command: str | None) -> Path | None:
    if not command:
        return None
    command = command.strip()
    if command.startswith('"') and '"' in command[1:]:
        return Path(command.split('"', 2)[1]).resolve()
    first = command.split(maxsplit=1)[0]
    return Path(first).resolve() if first else None


def get_startup_command() -> str | None:
    if os.name != "nt":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None


def set_startup(enabled: bool, executable: Path) -> None:
    if os.name != "nt":
        raise OSError("Startup registration is only supported on Windows")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                STARTUP_VALUE_NAME,
                0,
                winreg.REG_SZ,
                startup_command(executable),
            )
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass


def launch_background(executable: Path) -> None:
    target = executable.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Background executable does not exist: {target}")
    flags = (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    subprocess.Popen(
        [str(target), "--background"],
        cwd=str(target.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )


def background_instance_running(executable: Path) -> bool:
    target = os.path.normcase(str(executable.expanduser().resolve()))
    try:
        import psutil

        for process in psutil.process_iter(["exe", "cmdline"]):
            try:
                process_path = process.info.get("exe")
                command = process.info.get("cmdline") or []
                if process_path and os.path.normcase(str(Path(process_path).resolve())) == target and "--background" in command:
                    return True
            except (OSError, psutil.Error):
                continue
    except ImportError:
        return False
    return False


def stop_background_instances(executable: Path) -> None:
    target = os.path.normcase(str(executable.expanduser().resolve()))
    try:
        import psutil

        matches = []
        for process in psutil.process_iter(["pid", "exe", "cmdline"]):
            if process.pid == os.getpid():
                continue
            try:
                process_path = process.info.get("exe")
                command = process.info.get("cmdline") or []
                if process_path and os.path.normcase(str(Path(process_path).resolve())) == target and "--background" in command:
                    process.terminate()
                    matches.append(process)
            except (OSError, psutil.Error):
                continue
        _, alive = psutil.wait_procs(matches, timeout=5)
        for process in alive:
            process.kill()
    except ImportError:
        return


def install_application(
    source_executable: Path,
    install_directory: Path,
    config_values: Mapping[str, str | bool | float],
    *,
    start_with_windows: bool,
) -> Path:
    source = source_executable.resolve()
    if not source.is_file() or source.suffix.lower() != ".exe":
        raise ValueError("Installation is available from the packaged EXE only")

    destination_directory = install_directory.expanduser().resolve()
    destination_directory.mkdir(parents=True, exist_ok=True)
    destination = destination_directory / EXECUTABLE_NAME
    destination_config = destination_directory / CONFIG_FILENAME
    merged_values = dict(config_values)
    if destination_config.is_file():
        existing_values = read_config_values(destination_config)
        if existing_values.get("AIWM_TOKEN"):
            merged_values["AIWM_TOKEN"] = existing_values["AIWM_TOKEN"]

    stop_background_instances(destination)
    if source != destination:
        shutil.copy2(source, destination)
    device_id, device_name = automatic_device_identity()
    merged_values["AIWM_DEVICE_ID"] = device_id
    merged_values["AIWM_DEVICE_NAME"] = device_name
    write_agent_config(destination_config, merged_values)
    set_startup(start_with_windows, destination)
    return destination
