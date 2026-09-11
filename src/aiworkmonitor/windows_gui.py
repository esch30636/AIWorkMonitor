from __future__ import annotations

import ctypes
import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
import urllib.request
from contextlib import suppress
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from aiworkmonitor.config import AgentSettings
from aiworkmonitor.windows_agent import check_payload
from aiworkmonitor.windows_runtime import (
    CONFIG_FILENAME,
    DEFAULT_RELAY_PORT,
    EXECUTABLE_NAME,
    automatic_device_identity,
    background_instance_running,
    default_install_directory,
    ensure_agent_config,
    get_startup_command,
    install_application,
    launch_background,
    mobile_websocket_url,
    read_config_values,
    set_startup,
    startup_executable,
    stop_background_instances,
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
WARNING = "#FFD29A"


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


class WindowsAgentApp:
    def __init__(self, root: tk.Tk, proposed_config_path: Path) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.health_check_pending = False
        self.advanced_window: tk.Toplevel | None = None
        self.source_executable = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
        self.installed_executable: Path | None = None
        self.config_path = proposed_config_path
        self.loaded_values: dict[str, str] = {}

        self.root.title("AI Work Monitor")
        self.root.configure(bg=BACKGROUND)
        self.root.geometry("900x690")
        self.root.minsize(780, 620)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        with suppress(Exception):
            self.root.iconbitmap(default=str(_resource_path("assets/app_icon.ico")))

        self._resolve_installation()
        self._load_identity()
        self._build_ui()
        self._ensure_background_running()
        self.root.after(100, self._poll_events)
        self.root.after(350, self._request_health_check)

    def _resolve_installation(self) -> None:
        registered = startup_executable(get_startup_command())
        if registered and registered.is_file():
            self.installed_executable = registered
            self.config_path = registered.parent / CONFIG_FILENAME
            return
        if self.source_executable and self.config_path.is_file():
            self.installed_executable = self.source_executable

    def _load_identity(self) -> None:
        self.config_error: str | None = None
        try:
            self.loaded_values = ensure_agent_config(self.config_path)
        except (OSError, ValueError) as exc:
            self.config_error = str(exc)
            device_id, device_name = automatic_device_identity()
            self.loaded_values = {
                "AIWM_TOKEN": "",
                "AIWM_PORT": str(DEFAULT_RELAY_PORT),
                "AIWM_RELAY_URL": f"ws://127.0.0.1:{DEFAULT_RELAY_PORT}",
                "AIWM_DEVICE_ID": device_id,
                "AIWM_DEVICE_NAME": device_name,
                "AIWM_SAMPLE_INTERVAL": "2",
                "AIWM_ALLOW_CLAUDE_COMMANDS": "true",
            }

        self.port = int(self.loaded_values.get("AIWM_PORT", str(DEFAULT_RELAY_PORT)))
        self.device_name_var = tk.StringVar(value=socket.gethostname())
        self.mobile_url_var = tk.StringVar(value=mobile_websocket_url(self.port))
        self.token_var = tk.StringVar(value=self.loaded_values.get("AIWM_TOKEN", ""))
        self.status_var = tk.StringVar(value="正在启动后台服务" if self.installed_executable else "等待安装")
        self.status_detail_var = tk.StringVar(value="程序关闭后，监控仍会在后台运行。")
        self.install_dir_var = tk.StringVar(
            value=str(self.installed_executable.parent if self.installed_executable else default_install_directory())
        )
        self.interval_var = tk.StringVar(value=self.loaded_values.get("AIWM_SAMPLE_INTERVAL", "2"))
        self.allow_commands_var = tk.BooleanVar(
            value=_as_bool(self.loaded_values.get("AIWM_ALLOW_CLAUDE_COMMANDS"), default=True)
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BACKGROUND, padx=30, pady=22)
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
            text="此电脑已自动配置；请按下方内容连接手机",
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

        self.content = tk.Frame(self.root, bg=BACKGROUND, padx=28)
        self.content.pack(fill="both", expand=True)

        phone = self._panel(self.content, "在 Android 手机端这样填写")
        phone.pack(fill="x", pady=(0, 14))
        tk.Label(
            phone,
            text="先确认手机和电脑登录同一个 Tailscale 账户，然后在 APK 的连接页面逐项填写：",
            bg=PANEL,
            fg=MUTED,
            justify="left",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=20, pady=(6, 14))

        self._value_row(phone, "设备名称", self.device_name_var, self._copy_device_name)
        self._value_row(phone, "中继 WebSocket 地址", self.mobile_url_var, self._copy_mobile_url)
        self.token_entry = self._value_row(phone, "访问令牌", self.token_var, self._copy_token, secret=True)

        actions = tk.Frame(phone, bg=PANEL)
        actions.pack(fill="x", padx=20, pady=(10, 16))
        self._button(actions, "复制全部连接信息", self._copy_all).pack(side="left")
        self._button(actions, "显示 / 隐藏令牌", self._toggle_token, secondary=True).pack(side="left", padx=8)
        self._button(actions, "刷新地址", self._refresh_mobile_url, secondary=True).pack(side="left")

        service = self._panel(self.content, "后台运行状态")
        service.pack(fill="x", pady=(0, 14))
        tk.Label(
            service,
            textvariable=self.status_detail_var,
            bg=PANEL,
            fg=MUTED,
            justify="left",
            wraplength=790,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", padx=20, pady=(6, 10))
        service_actions = tk.Frame(service, bg=PANEL)
        service_actions.pack(fill="x", padx=20, pady=(0, 16))
        if not self.installed_executable:
            self.install_button = self._button(
                service_actions,
                "安装并开始永久后台运行",
                self._install,
            )
            self.install_button.pack(side="left", padx=(0, 8))
        self._button(service_actions, "检查后台服务", self._request_health_check, secondary=True).pack(side="left")
        self._button(service_actions, "高级设置", self._toggle_advanced, secondary=True).pack(side="left", padx=8)

        if not self.installed_executable:
            self.status_detail_var.set("首次使用请点击“安装并开始永久后台运行”。令牌已自动生成，安装后不会改变。")
        elif self.config_error:
            self.status_detail_var.set(f"配置读取失败：{self.config_error}")

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
            readonlybackground=FIELD,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            font=("Microsoft YaHei UI", 10),
        )

    def _value_row(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.StringVar,
        copy_command: Any,
        *,
        secret: bool = False,
    ) -> tk.Entry:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", padx=20, pady=5)
        tk.Label(row, text=label, width=20, anchor="w", bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).pack(
            side="left"
        )
        entry = self._entry(row, variable, show="●" if secret else None)
        entry.configure(state="readonly")
        entry.pack(side="left", fill="x", expand=True, ipady=7)
        self._button(row, "复制", copy_command, secondary=True, compact=True).pack(side="left", padx=(8, 0))
        return entry

    def _field(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky="w", padx=(18, 12), pady=7
        )
        self._entry(parent, variable).grid(row=row, column=1, sticky="ew", pady=7, ipady=7)
        tk.Frame(parent, width=18, bg=PANEL).grid(row=row, column=2)

    def _path_field(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, command: Any) -> None:
        tk.Label(parent, text=label, bg=PANEL, fg=MUTED, font=("Microsoft YaHei UI", 9)).grid(
            row=row, column=0, sticky="w", padx=(18, 12), pady=7
        )
        self._entry(parent, variable).grid(row=row, column=1, sticky="ew", pady=7, ipady=7)
        self._button(parent, "浏览", command, secondary=True, compact=True).grid(
            row=row, column=2, padx=(8, 18), pady=7
        )

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
            relief="flat",
            bd=0,
            padx=10 if compact else 16,
            pady=5 if compact else 8,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "bold"),
        )

    def _config_values(self) -> dict[str, str | bool | float]:
        interval = max(float(self.interval_var.get().strip()), 0.5)
        device_id, device_name = automatic_device_identity()
        return {
            **self.loaded_values,
            "AIWM_TOKEN": self.loaded_values.get("AIWM_TOKEN", self.token_var.get()),
            "AIWM_RELAY_URL": f"ws://127.0.0.1:{self.port}",
            "AIWM_PORT": self.port,
            "AIWM_DEVICE_ID": device_id,
            "AIWM_DEVICE_NAME": device_name,
            "AIWM_SAMPLE_INTERVAL": interval,
            "AIWM_ALLOW_CLAUDE_COMMANDS": self.allow_commands_var.get(),
        }

    def _settings(self) -> AgentSettings:
        values = self._config_values()
        token = str(values["AIWM_TOKEN"])
        if not token:
            raise ValueError("本机令牌尚未生成")
        return AgentSettings(
            token=token,
            relay_url=str(values["AIWM_RELAY_URL"]),
            device_id=str(values["AIWM_DEVICE_ID"]),
            device_name=str(values["AIWM_DEVICE_NAME"]),
            sample_interval=float(values["AIWM_SAMPLE_INTERVAL"]),
            allow_claude_commands=bool(values["AIWM_ALLOW_CLAUDE_COMMANDS"]),
            claude_log_glob=self.loaded_values.get("AIWM_CLAUDE_LOG_GLOB"),
            chatgpt_log_glob=self.loaded_values.get("AIWM_CHATGPT_LOG_GLOB"),
        )

    def _save_advanced(self, *, notify: bool = True) -> bool:
        try:
            self._settings()
            write_agent_config(self.config_path, self._config_values())
            self.loaded_values = read_config_values(self.config_path, required=True)
            if self.installed_executable:
                set_startup(True, self.installed_executable)
                stop_background_instances(self.installed_executable)
                launch_background(self.installed_executable)
            if notify:
                messagebox.showinfo("设置已保存", "后台服务已自动重启。设备名称和本机令牌保持不变。")
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法保存设置", str(exc))
            return False

    def _install(self) -> None:
        if not self.source_executable:
            messagebox.showwarning("仅打包版可安装", "请构建并运行 AIWorkMonitorAgent.exe。")
            return
        try:
            requested_destination = Path(self.install_dir_var.get()).expanduser().resolve() / EXECUTABLE_NAME
            if self.installed_executable and self.installed_executable.resolve() != requested_destination:
                stop_background_instances(self.installed_executable)
            destination = install_application(
                self.source_executable,
                Path(self.install_dir_var.get()),
                self._config_values(),
                start_with_windows=True,
            )
            self.installed_executable = destination
            self.config_path = destination.parent / CONFIG_FILENAME
            self.loaded_values = ensure_agent_config(self.config_path)
            self.token_var.set(self.loaded_values["AIWM_TOKEN"])
            self.install_dir_var.set(str(destination.parent))
            launch_background(destination)
            self.status_var.set("正在启动后台服务")
            self.status_detail_var.set("安装完成。以后开机自动运行；关闭此窗口不会停止监控。")
            self.root.after(800, self._request_health_check)
            messagebox.showinfo(
                "安装完成",
                f"已安装到：\n{destination}\n\n后台服务已启动，并已设置为开机自动运行。\n本机令牌今后保持不变。",
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("安装失败", str(exc))

    def _ensure_background_running(self) -> None:
        if not self.installed_executable:
            return
        try:
            set_startup(True, self.installed_executable)
            if not background_instance_running(self.installed_executable):
                launch_background(self.installed_executable)
        except OSError as exc:
            self.status_var.set("后台启动失败")
            self.status_detail_var.set(str(exc))

    def _request_health_check(self) -> None:
        if self.health_check_pending:
            return
        self.health_check_pending = True

        def worker() -> None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=1.5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.events.put(("health", payload))
            except Exception as exc:
                self.events.put(("health_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "health":
                self.health_check_pending = False
                self.status_var.set("后台服务运行中")
                self.status_label.configure(bg=PRIMARY_DARK, fg=PRIMARY)
                device_count = payload.get("deviceCount", 0)
                self.status_detail_var.set(
                    f"后台中继与本机监控均已启动（当前设备数：{device_count}）。关闭此窗口不会停止运行。"
                )
            elif kind == "health_error":
                self.health_check_pending = False
                if self.installed_executable:
                    self.status_var.set("后台服务正在恢复")
                    self.status_label.configure(bg="#4A3725", fg=WARNING)
                    self.status_detail_var.set("后台服务尚未就绪，程序会自动持续重试。可稍后点击“检查后台服务”。")
                else:
                    self.status_var.set("等待安装")
            elif kind == "check":
                telemetry = payload.get("telemetry", {})
                cpu = telemetry.get("cpu", {}).get("usagePercent", "--")
                memory = telemetry.get("memory", {}).get("usagePercent", "--")
                gpu_count = len(telemetry.get("gpus", []))
                messagebox.showinfo("本机检测完成", f"CPU：{cpu}%\n内存：{memory}%\nGPU：{gpu_count} 个")
            elif kind == "error":
                messagebox.showerror("操作失败", str(payload))
        self.root.after(100, self._poll_events)

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

    def _toggle_advanced(self) -> None:
        if self.advanced_window and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            self.advanced_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.advanced_window = window
        window.title("AI Work Monitor · 高级设置")
        window.configure(bg=BACKGROUND)
        window.geometry("800x380")
        window.minsize(720, 350)
        window.transient(self.root)
        with suppress(Exception):
            window.iconbitmap(default=str(_resource_path("assets/app_icon.ico")))

        advanced = self._panel(window, "高级设置（通常无需修改）")
        advanced.pack(fill="both", expand=True, padx=22, pady=22)
        advanced.grid_columnconfigure(1, weight=1)
        self._path_field(advanced, 0, "安装位置", self.install_dir_var, self._browse_install)
        self._field(advanced, 1, "采样间隔（秒）", self.interval_var)
        tk.Checkbutton(
            advanced,
            text="允许手机向 Claude Code 发送指令",
            variable=self.allow_commands_var,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=FIELD,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=18, pady=(8, 12))
        advanced_actions = tk.Frame(advanced, bg=PANEL)
        advanced_actions.grid(row=3, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 18))
        self._button(advanced_actions, "安装 / 更新并保持后台运行", self._install).pack(side="left")
        self._button(advanced_actions, "保存高级设置", self._save_advanced, secondary=True).pack(side="left", padx=8)
        self._button(advanced_actions, "检测本机硬件", self._check_local, secondary=True).pack(side="left")

    def _refresh_mobile_url(self) -> None:
        self.mobile_url_var.set(mobile_websocket_url(self.port))
        self._request_health_check()

    def _toggle_token(self) -> None:
        self.token_entry.configure(state="normal")
        self.token_entry.configure(show="" if self.token_entry.cget("show") else "●")
        self.token_entry.configure(state="readonly")

    def _copy(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update_idletasks()

    def _copy_device_name(self) -> None:
        self._copy(self.device_name_var.get())

    def _copy_mobile_url(self) -> None:
        self._copy(self.mobile_url_var.get())

    def _copy_token(self) -> None:
        self._copy(self.token_var.get())

    def _copy_all(self) -> None:
        self._copy(
            "设备名称：{name}\n中继 WebSocket 地址：{url}\n访问令牌：{token}".format(
                name=self.device_name_var.get(),
                url=self.mobile_url_var.get(),
                token=self.token_var.get(),
            )
        )

    def _browse_install(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.install_dir_var.get() or str(default_install_directory()))
        if selected:
            self.install_dir_var.set(selected)

    def _close(self) -> None:
        self.root.destroy()


def launch_windows_gui(config_path: Path) -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    WindowsAgentApp(root, config_path)
    root.mainloop()
