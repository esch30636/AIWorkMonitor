from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from contextlib import suppress
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Any

from aiworkmonitor.agent import DesktopAgent
from aiworkmonitor.config import AgentSettings
from aiworkmonitor.windows_agent import check_payload
from aiworkmonitor.windows_runtime import (
    EXECUTABLE_NAME,
    default_install_directory,
    get_startup_command,
    install_application,
    read_config_values,
    set_startup,
    write_agent_config,
)


BACKGROUND = "#10131A"
PANEL = "#191E28"
FIELD = "#232A36"
TEXT = "#F0F4FA"
MUTED = "#A8B0BE"
PRIMARY = "#70D7A7"
PRIMARY_DARK = "#174C38"
BORDER = "#333B49"


def _enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    with suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    with suppress(Exception):
        ctypes.windll.user32.SetProcessDPIAware()


def _resource_path(relative: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / relative
    return Path(__file__).resolve().parents[2] / "packaging" / "windows" / "app_icon.ico"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class QueueLogHandler(logging.Handler):
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        self.events.put(("log", message))
        raw = record.getMessage()
        if "Connected to relay" in raw:
            self.events.put(("state", "已连接"))
        elif "Relay connection failed" in raw:
            self.events.put(("state", "连接失败，正在重试"))


class WindowsAgentApp:
    def __init__(self, root: tk.Tk, config_path: Path) -> None:
        self.root = root
        self.config_path = config_path
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.agent_thread: threading.Thread | None = None
        self.loaded_values: dict[str, str] = {}

        self.root.title("AI Work Monitor")
        self.root.configure(bg=BACKGROUND)
        self.root.geometry("1040x760")
        self.root.minsize(900, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        with suppress(Exception):
            self.root.iconbitmap(default=str(_resource_path("assets/app_icon.ico")))

        self._load_variables()
        self._build_ui()
        self._configure_logging()
        self.root.after(100, self._poll_events)

    def _load_variables(self) -> None:
        error: str | None = None
        try:
            self.loaded_values = read_config_values(self.config_path)
        except (OSError, ValueError) as exc:
            error = str(exc)
            self.loaded_values = {}

        defaults = AgentSettings.from_env()
        values = self.loaded_values
        saved_startup = get_startup_command()
        install_path = default_install_directory()
        if saved_startup and saved_startup.startswith('"'):
            candidate = Path(saved_startup.split('"', 2)[1])
            if candidate.name.lower() == EXECUTABLE_NAME.lower():
                install_path = candidate.parent

        self.relay_var = tk.StringVar(value=values.get("AIWM_RELAY_URL", defaults.relay_url))
        saved_token = values.get("AIWM_TOKEN", defaults.token)
        self.token_var = tk.StringVar(value="" if saved_token == "development-token" else saved_token)
        self.device_id = values.get("AIWM_DEVICE_ID", defaults.device_id)
        self.device_name_var = tk.StringVar(value=values.get("AIWM_DEVICE_NAME", socket.gethostname()))
        self.interval_var = tk.StringVar(value=values.get("AIWM_SAMPLE_INTERVAL", "2"))
        self.workdir_var = tk.StringVar(value=values.get("AIWM_CLAUDE_WORKDIR", str(defaults.claude_workdir)))
        self.allow_commands_var = tk.BooleanVar(value=_as_bool(values.get("AIWM_ALLOW_CLAUDE_COMMANDS")))
        self.install_dir_var = tk.StringVar(value=str(install_path))
        self.startup_var = tk.BooleanVar(value=saved_startup is not None)
        self.status_var = tk.StringVar(value="未运行")
        self.config_error = error

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BACKGROUND, padx=28, pady=20)
        header.pack(fill="x")
        title_box = tk.Frame(header, bg=BACKGROUND)
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="AI Work Monitor",
            bg=BACKGROUND,
            fg=TEXT,
            font=("Microsoft YaHei UI", 22, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="Windows 代理控制台 · 实时监控 Claude Code 与 ChatGPT",
            bg=BACKGROUND,
            fg=MUTED,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(3, 0))
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=FIELD,
            fg=MUTED,
            padx=16,
            pady=8,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.status_label.pack(side="right")

        content = tk.Frame(self.root, bg=BACKGROUND, padx=24)
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3, uniform="panels")
        content.grid_columnconfigure(1, weight=2, uniform="panels")
        content.grid_rowconfigure(1, weight=1)

        settings = self._panel(content, "连接设置")
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        settings.grid_columnconfigure(1, weight=1)
        self._field(settings, 0, "中继 WebSocket 地址", self.relay_var)
        self._field(settings, 1, "访问令牌", self.token_var, show="●")
        self._field(settings, 2, "设备名称", self.device_name_var)
        self._field(settings, 3, "采样间隔（秒）", self.interval_var)
        self._path_field(settings, 4, "Claude 工作目录", self.workdir_var, self._browse_workdir)
        tk.Checkbutton(
            settings,
            text="允许手机向 Claude Code 发送指令",
            variable=self.allow_commands_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=FIELD,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=18, pady=(8, 12))
        settings_actions = tk.Frame(settings, bg=PANEL)
        settings_actions.grid(row=6, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 18))
        self._button(settings_actions, "保存配置", self._save_config).pack(side="left")
        self._button(settings_actions, "检测本机", self._check_local, secondary=True).pack(side="left", padx=8)

        right = tk.Frame(content, bg=BACKGROUND)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        right.grid_columnconfigure(0, weight=1)

        runtime = self._panel(right, "代理运行")
        runtime.pack(fill="x", pady=(0, 12))
        tk.Label(
            runtime,
            text="启动后会持续上传电脑硬件遥测与 AI 应用状态。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=330,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=18, pady=(4, 14))
        runtime_actions = tk.Frame(runtime, bg=PANEL)
        runtime_actions.pack(fill="x", padx=18, pady=(0, 18))
        self.start_button = self._button(runtime_actions, "启动 Agent", self._start_agent)
        self.start_button.pack(side="left")
        self.stop_button = self._button(runtime_actions, "停止", self._stop_agent, secondary=True)
        self.stop_button.pack(side="left", padx=8)
        self.stop_button.configure(state="disabled")

        install = self._panel(right, "安装与开机启动")
        install.pack(fill="both", expand=True)
        tk.Label(
            install,
            text="选择安装目录。安装后可用当前 Windows 账户静默开机启动，无需管理员权限。",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=330,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=18, pady=(4, 12))
        install_row = tk.Frame(install, bg=PANEL)
        install_row.pack(fill="x", padx=18)
        self._entry(install_row, self.install_dir_var).pack(side="left", fill="x", expand=True)
        self._button(install_row, "浏览", self._browse_install, secondary=True).pack(side="left", padx=(8, 0))
        tk.Checkbutton(
            install,
            text="开机自动启动 Agent（后台运行）",
            variable=self.startup_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=FIELD,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=18, pady=14)
        install_actions = tk.Frame(install, bg=PANEL)
        install_actions.pack(fill="x", padx=18, pady=(0, 18))
        self._button(install_actions, "安装 / 更新", self._install).pack(side="left")
        self._button(install_actions, "应用启动设置", self._apply_startup, secondary=True).pack(side="left", padx=8)

        logs = self._panel(content, "运行日志")
        logs.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 20))
        logs.grid_rowconfigure(0, weight=1)
        logs.grid_columnconfigure(0, weight=1)
        self.log_text = ScrolledText(
            logs,
            bg="#0C0F15",
            fg="#CBD3DF",
            insertbackground=TEXT,
            relief="flat",
            borderwidth=0,
            font=("Cascadia Mono", 9),
            padx=12,
            pady=10,
            height=10,
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=14, pady=(4, 14))

        if self.config_error:
            self._append_log(f"配置读取失败：{self.config_error}")

    def _panel(self, parent: tk.Misc, title: str) -> tk.LabelFrame:
        return tk.LabelFrame(
            parent,
            text=f"  {title}  ",
            bg=PANEL,
            fg=TEXT,
            bd=1,
            relief="solid",
            highlightbackground=BORDER,
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=2,
            pady=8,
        )

    def _entry(self, parent: tk.Misc, variable: tk.StringVar, *, show: str | None = None) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=variable,
            show=show or "",
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=PRIMARY_DARK,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            font=("Microsoft YaHei UI", 10),
        )

    def _field(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, *, show: str | None = None) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(18, 12),
            pady=7,
        )
        entry = self._entry(parent, variable, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=7, ipady=7)
        if show:
            self._button(
                parent,
                "显示",
                lambda: entry.configure(show="" if entry.cget("show") else show),
                secondary=True,
                compact=True,
            ).grid(row=row, column=2, padx=(8, 18), pady=7)
        else:
            tk.Frame(parent, width=18, bg=PANEL).grid(row=row, column=2)

    def _path_field(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, command: Any) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(18, 12),
            pady=7,
        )
        self._entry(parent, variable).grid(row=row, column=1, sticky="ew", pady=7, ipady=7)
        self._button(parent, "浏览", command, secondary=True, compact=True).grid(row=row, column=2, padx=(8, 18), pady=7)

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Any,
        *,
        secondary: bool = False,
        compact: bool = False,
    ) -> tk.Button:
        background = FIELD if secondary else PRIMARY
        foreground = TEXT if secondary else "#082418"
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=BORDER if secondary else "#8BE8BD",
            activeforeground=foreground,
            disabledforeground=MUTED,
            relief="flat",
            bd=0,
            padx=10 if compact else 16,
            pady=5 if compact else 8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )

    def _configure_logging(self) -> None:
        handler = QueueLogHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        self.log_handler = handler

    def _config_values(self) -> dict[str, str | bool | float]:
        interval = max(float(self.interval_var.get().strip()), 0.5)
        return {
            "AIWM_TOKEN": self.token_var.get().strip(),
            "AIWM_RELAY_URL": self.relay_var.get().strip().rstrip("/"),
            "AIWM_DEVICE_ID": self.device_id,
            "AIWM_DEVICE_NAME": self.device_name_var.get().strip(),
            "AIWM_SAMPLE_INTERVAL": interval,
            "AIWM_ALLOW_CLAUDE_COMMANDS": self.allow_commands_var.get(),
            "AIWM_CLAUDE_WORKDIR": str(Path(self.workdir_var.get().strip()).expanduser().resolve()),
            **{
                key: value
                for key, value in self.loaded_values.items()
                if key in {"AIWM_CLAUDE_LOG_GLOB", "AIWM_CHATGPT_LOG_GLOB"} and value
            },
        }

    def _settings(self) -> AgentSettings:
        values = self._config_values()
        relay = str(values["AIWM_RELAY_URL"])
        token = str(values["AIWM_TOKEN"])
        name = str(values["AIWM_DEVICE_NAME"])
        if not relay.startswith(("ws://", "wss://")):
            raise ValueError("中继地址必须以 ws:// 或 wss:// 开头")
        if not token:
            raise ValueError("访问令牌不能为空")
        if not name:
            raise ValueError("设备名称不能为空")
        return AgentSettings(
            token=token,
            relay_url=relay,
            device_id=self.device_id,
            device_name=name,
            sample_interval=float(values["AIWM_SAMPLE_INTERVAL"]),
            allow_claude_commands=bool(values["AIWM_ALLOW_CLAUDE_COMMANDS"]),
            claude_workdir=Path(str(values["AIWM_CLAUDE_WORKDIR"])),
            claude_log_glob=self.loaded_values.get("AIWM_CLAUDE_LOG_GLOB"),
            chatgpt_log_glob=self.loaded_values.get("AIWM_CHATGPT_LOG_GLOB"),
        )

    def _save_config(self, *, notify: bool = True) -> bool:
        try:
            self._settings()
            write_agent_config(self.config_path, self._config_values())
            self.loaded_values = read_config_values(self.config_path)
            self._append_log(f"配置已保存：{self.config_path}")
            if notify:
                messagebox.showinfo("保存成功", "配置已保存，访问令牌已使用 Windows DPAPI 保护。")
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法保存配置", str(exc))
            return False

    def _start_agent(self) -> None:
        if self.agent_thread and self.agent_thread.is_alive():
            return
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("配置不完整", str(exc))
            return
        if not self._save_config(notify=False):
            return

        self.stop_event.clear()
        self.agent_thread = threading.Thread(target=self._agent_worker, args=(settings,), daemon=True)
        self.agent_thread.start()
        self.status_var.set("正在连接")
        self.status_label.configure(bg="#314154", fg=TEXT)
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._append_log("Agent 已启动")

    def _agent_worker(self, settings: AgentSettings) -> None:
        async def run() -> None:
            task = asyncio.create_task(DesktopAgent(settings).run_forever())
            while not self.stop_event.is_set():
                await asyncio.sleep(0.2)
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        try:
            asyncio.run(run())
        except Exception as exc:
            self.events.put(("log", f"Agent 异常退出：{exc}"))
        finally:
            self.events.put(("stopped", None))

    def _stop_agent(self) -> None:
        if self.agent_thread and self.agent_thread.is_alive():
            self.stop_event.set()
            self.status_var.set("正在停止")
            self.stop_button.configure(state="disabled")

    def _check_local(self) -> None:
        try:
            settings = self._settings()
        except ValueError as exc:
            messagebox.showerror("配置不完整", str(exc))
            return

        def worker() -> None:
            try:
                self.events.put(("check", check_payload(settings)))
            except Exception as exc:
                self.events.put(("error", f"本机检测失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self._append_log("正在采集本机硬件与应用状态…")

    def _install(self) -> None:
        if not getattr(sys, "frozen", False):
            messagebox.showwarning("仅打包版可安装", "请先构建并运行 AIWorkMonitorAgent.exe。")
            return
        try:
            self._settings()
            destination = install_application(
                Path(sys.executable),
                Path(self.install_dir_var.get()),
                self._config_values(),
                start_with_windows=self.startup_var.get(),
            )
            self._append_log(f"应用已安装：{destination}")
            messagebox.showinfo(
                "安装完成",
                f"已安装到：\n{destination}\n\n开机启动：{'已启用' if self.startup_var.get() else '未启用'}",
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("安装失败", str(exc))

    def _apply_startup(self) -> None:
        target = Path(self.install_dir_var.get()).expanduser().resolve() / EXECUTABLE_NAME
        if self.startup_var.get() and not target.is_file():
            messagebox.showwarning("尚未安装", "目标目录中没有 EXE，请先点击“安装 / 更新”。")
            return
        try:
            set_startup(self.startup_var.get(), target)
            state = "已启用" if self.startup_var.get() else "已关闭"
            self._append_log(f"开机启动{state}")
            messagebox.showinfo("启动设置", f"开机自动启动已{state}。")
        except OSError as exc:
            messagebox.showerror("设置失败", str(exc))

    def _browse_workdir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.workdir_var.get() or str(Path.home()))
        if selected:
            self.workdir_var.set(selected)

    def _browse_install(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.install_dir_var.get() or str(default_install_directory()))
        if selected:
            self.install_dir_var.set(selected)

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(payload))
            elif kind == "state":
                self.status_var.set(str(payload))
                if payload == "已连接":
                    self.status_label.configure(bg=PRIMARY_DARK, fg=PRIMARY)
                else:
                    self.status_label.configure(bg="#4A3725", fg="#FFD29A")
            elif kind == "stopped":
                self.status_var.set("未运行")
                self.status_label.configure(bg=FIELD, fg=MUTED)
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self._append_log("Agent 已停止")
            elif kind == "check":
                self._append_log(json.dumps(payload, ensure_ascii=False, indent=2))
                telemetry = payload.get("telemetry", {})
                cpu = telemetry.get("cpu", {}).get("usagePercent", "--")
                memory = telemetry.get("memory", {}).get("usagePercent", "--")
                gpu_count = len(telemetry.get("gpus", []))
                messagebox.showinfo("本机检测完成", f"CPU：{cpu}%\n内存：{memory}%\nGPU：{gpu_count} 个\n\n详细结果已写入运行日志。")
            elif kind == "error":
                self._append_log(str(payload))
                messagebox.showerror("操作失败", str(payload))
        self.root.after(100, self._poll_events)

    def _append_log(self, message: str) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _close(self) -> None:
        self.stop_event.set()
        logging.getLogger().removeHandler(self.log_handler)
        self.root.destroy()


def launch_windows_gui(config_path: Path) -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    WindowsAgentApp(root, config_path)
    root.mainloop()
