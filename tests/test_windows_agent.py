from pathlib import Path

import pytest

from aiworkmonitor.windows_agent import load_config_file
from aiworkmonitor import windows_runtime
from aiworkmonitor.windows_runtime import (
    CONFIG_FILENAME,
    EXECUTABLE_NAME,
    background_instance_running,
    ensure_agent_config,
    install_application,
    read_config_values,
    startup_command,
    startup_executable,
    write_agent_config,
)


def test_load_config_file_uses_aiwm_keys_and_preserves_environment(tmp_path, monkeypatch) -> None:
    config = tmp_path / "aiworkmonitor.env"
    config.write_text(
        "AIWM_TOKEN=file-token\n"
        "AIWM_DEVICE_NAME=Office PC\n"
        "AIWM_CLAUDE_LOG_GLOB=claude/**/*.jsonl\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIWM_TOKEN", "environment-token")

    assert load_config_file(config)
    assert __import__("os").environ["AIWM_TOKEN"] == "environment-token"
    assert __import__("os").environ["AIWM_DEVICE_NAME"] == "Office PC"
    assert __import__("os").environ["AIWM_CLAUDE_LOG_GLOB"] == "claude/**/*.jsonl"


def test_load_config_file_rejects_unknown_keys(tmp_path) -> None:
    config = tmp_path / "aiworkmonitor.env"
    config.write_text("PATH=unsafe\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported key"):
        load_config_file(config)


def test_write_agent_config_round_trips_protected_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(windows_runtime, "_protect_secret", lambda value: f"protected:{value[::-1]}")
    monkeypatch.setattr(windows_runtime, "_unprotect_secret", lambda value: value.removeprefix("protected:")[::-1])
    config = tmp_path / CONFIG_FILENAME

    write_agent_config(
        config,
        {
            "AIWM_TOKEN": "secret-token",
            "AIWM_RELAY_URL": "ws://relay.example:8765",
            "AIWM_DEVICE_NAME": "Office PC",
            "AIWM_SAMPLE_INTERVAL": 2,
            "AIWM_ALLOW_CLAUDE_COMMANDS": True,
        },
    )

    raw = config.read_text(encoding="utf-8")
    assert "AIWM_TOKEN_DPAPI=protected:nekot-terces" in raw
    assert "AIWM_TOKEN=secret-token" not in raw
    values = read_config_values(config)
    assert values["AIWM_TOKEN"] == "secret-token"
    assert values["AIWM_ALLOW_CLAUDE_COMMANDS"] == "true"


def test_startup_command_quotes_install_path(tmp_path) -> None:
    executable = tmp_path / "Program Files" / EXECUTABLE_NAME
    assert startup_command(executable) == f'"{executable.resolve()}" --background'
    assert startup_executable(startup_command(executable)) == executable.resolve()


def test_background_instance_running_matches_executable_and_mode(tmp_path, monkeypatch) -> None:
    executable = (tmp_path / EXECUTABLE_NAME).resolve()

    class FakeProcess:
        info = {"exe": str(executable), "cmdline": [str(executable), "--background"]}

    monkeypatch.setattr("psutil.process_iter", lambda fields: [FakeProcess()])
    assert background_instance_running(executable)


def test_ensure_agent_config_generates_token_once_and_uses_hostname(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(windows_runtime, "_protect_secret", lambda value: f"protected:{value}")
    monkeypatch.setattr(windows_runtime, "_unprotect_secret", lambda value: value.removeprefix("protected:"))
    monkeypatch.setattr(windows_runtime, "automatic_device_identity", lambda: ("windows-DESKTOP", "DESKTOP"))
    config = tmp_path / CONFIG_FILENAME

    first = ensure_agent_config(config, token_factory=lambda: "permanent-token")
    second = ensure_agent_config(config, token_factory=lambda: "must-not-be-used")

    assert first["AIWM_TOKEN"] == "permanent-token"
    assert second["AIWM_TOKEN"] == "permanent-token"
    assert second["AIWM_DEVICE_ID"] == "windows-DESKTOP"
    assert second["AIWM_DEVICE_NAME"] == "DESKTOP"
    assert second["AIWM_RELAY_URL"] == "ws://127.0.0.1:8765"
    assert second["AIWM_ALLOW_CLAUDE_COMMANDS"] == "true"


def test_install_application_copies_executable_and_configures_startup(tmp_path, monkeypatch) -> None:
    source = tmp_path / "download" / "setup.exe"
    source.parent.mkdir()
    source.write_bytes(b"portable-executable")
    install_directory = tmp_path / "custom install"
    startup_calls: list[tuple[bool, Path]] = []
    monkeypatch.setattr(
        windows_runtime,
        "set_startup",
        lambda enabled, executable: startup_calls.append((enabled, executable)),
    )
    monkeypatch.setattr(windows_runtime, "stop_background_instances", lambda executable: None)

    installed = install_application(
        source,
        install_directory,
        {
            "AIWM_TOKEN": "test-token",
            "AIWM_RELAY_URL": "ws://relay.example:8765",
            "AIWM_DEVICE_NAME": "Office PC",
        },
        start_with_windows=True,
    )

    assert installed == install_directory / EXECUTABLE_NAME
    assert installed.read_bytes() == source.read_bytes()
    assert read_config_values(install_directory / CONFIG_FILENAME)["AIWM_TOKEN"] == "test-token"
    assert startup_calls == [(True, installed)]


def test_install_application_preserves_existing_machine_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(windows_runtime, "_protect_secret", lambda value: f"protected:{value}")
    monkeypatch.setattr(windows_runtime, "_unprotect_secret", lambda value: value.removeprefix("protected:"))
    monkeypatch.setattr(windows_runtime, "set_startup", lambda enabled, executable: None)
    monkeypatch.setattr(windows_runtime, "stop_background_instances", lambda executable: None)
    source = tmp_path / "download" / "setup.exe"
    source.parent.mkdir()
    source.write_bytes(b"new-version")
    install_directory = tmp_path / "installed"
    write_agent_config(install_directory / CONFIG_FILENAME, {"AIWM_TOKEN": "original-token"})

    install_application(
        source,
        install_directory,
        {"AIWM_TOKEN": "download-token"},
        start_with_windows=True,
    )

    assert read_config_values(install_directory / CONFIG_FILENAME)["AIWM_TOKEN"] == "original-token"
