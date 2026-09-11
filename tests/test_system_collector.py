import subprocess

from aiworkmonitor.collectors import system
from aiworkmonitor.collectors.system import SystemCollector


def test_system_collector_returns_portable_shape() -> None:
    sample = SystemCollector().sample()
    assert 0 <= sample["cpu"]["usagePercent"] <= 100
    assert sample["memory"]["usedBytes"] > 0
    assert sample["memory"]["totalBytes"] >= sample["memory"]["usedBytes"]
    assert isinstance(sample["gpus"], list)


def test_windows_telemetry_helpers_never_open_a_console(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(system.platform, "system", lambda: "Windows")
    monkeypatch.setattr(system.subprocess, "run", fake_run)

    system._run_hidden(["powershell", "-NoProfile"], capture_output=True, text=True)

    assert captured["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert captured["command"] == ["powershell", "-NoProfile"]
