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
            "gpus": self._nvidia_gpus(),
        }
        if platform.system() == "Windows":
            self._merge_libre_hardware_monitor(payload)
        return payload

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
