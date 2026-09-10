from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil


def _number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


class SystemCollector:
    def __init__(self) -> None:
        self._rapl_sample: tuple[float, float] | None = None
        self._windows_gpu = WindowsGpuCollector() if platform.system() == "Windows" else None
        psutil.cpu_percent(interval=None)

    def sample(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        payload: dict[str, Any] = {
            "cpu": {
                "usagePercent": round(psutil.cpu_percent(interval=None), 2),
                "temperatureC": self._cpu_temperature(),
                "powerW": self._cpu_power(),
            },
            "memory": {
                "usedBytes": int(memory.used),
                "totalBytes": int(memory.total),
                "usagePercent": round(memory.percent, 2),
            },
            "gpus": self._gpus(),
        }
        if platform.system() == "Windows":
            self._merge_libre_hardware_monitor(payload)
        return payload

    def _gpus(self) -> list[dict[str, Any]]:
        nvidia = self._nvidia_gpus()
        if nvidia:
            return nvidia
        if self._windows_gpu:
            sample = self._windows_gpu.sample()
            return [sample] if sample else []
        return []

    def _cpu_temperature(self) -> float | None:
        try:
            groups = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return None
        preferred: list[float] = []
        fallback: list[float] = []
        for entries in groups.values():
            for entry in entries:
                current = _number(entry.current)
                if current is None or current <= 0:
                    continue
                fallback.append(current)
                label = (entry.label or "").lower()
                if "package" in label or "tdie" in label or "tctl" in label:
                    preferred.append(current)
        values = preferred or fallback
        return max(values) if values else None

    def _cpu_power(self) -> float | None:
        if platform.system() != "Linux":
            return None
        paths = list(Path("/sys/class/powercap").glob("intel-rapl:*/energy_uj"))
        if not paths:
            return None
        try:
            readings = [float(path.read_text(encoding="utf-8").strip()) for path in paths]
            energy_j = sum(readings) / 1_000_000
        except (OSError, ValueError):
            return None
        now = time.monotonic()
        previous = self._rapl_sample
        self._rapl_sample = (now, energy_j)
        if previous is None or energy_j < previous[1] or now <= previous[0]:
            return None
        return round((energy_j - previous[1]) / (now - previous[0]), 2)

    def _nvidia_gpus(self) -> list[dict[str, Any]]:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return []
        fields = [
            "index",
            "name",
            "temperature.gpu",
            "power.draw",
            "utilization.gpu",
            "memory.used",
            "memory.total",
        ]
        try:
            result = subprocess.run(
                [executable, f"--query-gpu={','.join(fields)}", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=4,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        gpus: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) != len(fields):
                continue
            gpus.append(
                {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "temperatureC": _number(parts[2]),
                    "powerW": _number(parts[3]),
                    "usagePercent": _number(parts[4]),
                    "memoryUsedBytes": int(float(parts[5]) * 1024 * 1024),
                    "memoryTotalBytes": int(float(parts[6]) * 1024 * 1024),
                }
            )
        return gpus

    def _merge_libre_hardware_monitor(self, payload: dict[str, Any]) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return
        script = (
            "Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor "
            "-ErrorAction SilentlyContinue | Where-Object { $_.SensorType -in @('Temperature','Power') } | "
            "Select-Object Name,SensorType,Value | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return
            sensors = json.loads(result.stdout)
            if isinstance(sensors, dict):
                sensors = [sensors]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return
        for sensor in sensors:
            name = str(sensor.get("Name", "")).lower()
            kind = sensor.get("SensorType")
            value = _number(sensor.get("Value"))
            if value is None:
                continue
            if kind == "Temperature" and ("cpu package" in name or "core max" in name):
                payload["cpu"]["temperatureC"] = value
            elif kind == "Power" and ("cpu package" in name or "package" == name):
                payload["cpu"]["powerW"] = value


class WindowsGpuCollector:
    """Low-overhead Windows GPU fallback using persistent PDH counters."""

    def __init__(self) -> None:
        self._pdh: Any | None = None
        self._query: Any | None = None
        self._usage: Any | None = None
        self._dedicated: Any | None = None
        self._shared: Any | None = None
        self.name = "Windows GPU"
        self.total_bytes = 0
        self._load_inventory()
        try:
            import win32pdh

            self._pdh = win32pdh
            self._query = win32pdh.OpenQuery()
            self._usage = win32pdh.AddEnglishCounter(
                self._query, r"\GPU Engine(*)\Utilization Percentage"
            )
            self._dedicated = win32pdh.AddEnglishCounter(
                self._query, r"\GPU Adapter Memory(*)\Dedicated Usage"
            )
            self._shared = win32pdh.AddEnglishCounter(
                self._query, r"\GPU Adapter Memory(*)\Shared Usage"
            )
            win32pdh.CollectQueryData(self._query)
        except Exception:  # Hardware counters are optional and vary by driver.
            self._pdh = None
            self._query = None

    def _load_inventory(self) -> None:
        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            return
        script = (
            "Get-CimInstance Win32_VideoController | "
            "Where-Object { $_.Name -notmatch 'MuMu Virtual' } | "
            "Select-Object -First 1 Name,AdapterRAM | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                adapter = json.loads(result.stdout)
                self.name = str(adapter.get("Name") or self.name)
                self.total_bytes = int(adapter.get("AdapterRAM") or 0)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            return

    def sample(self) -> dict[str, Any] | None:
        if not self._pdh or self._query is None:
            return None
        try:
            self._pdh.CollectQueryData(self._query)
            usage = self._pdh.GetFormattedCounterArray(self._usage, self._pdh.PDH_FMT_DOUBLE)
            dedicated = self._pdh.GetFormattedCounterArray(self._dedicated, self._pdh.PDH_FMT_LARGE)
            shared = self._pdh.GetFormattedCounterArray(self._shared, self._pdh.PDH_FMT_LARGE)
        except Exception:  # Keep telemetry alive when a counter disappears.
            return None
        usage_percent = max((float(value) for value in usage.values()), default=0.0)
        memory_used = max(
            max((int(value) for value in dedicated.values()), default=0),
            max((int(value) for value in shared.values()), default=0),
        )
        return {
            "index": 0,
            "name": self.name,
            "temperatureC": None,
            "powerW": None,
            "usagePercent": round(min(usage_percent, 100.0), 2),
            "memoryUsedBytes": memory_used,
            "memoryTotalBytes": self.total_bytes,
        }
