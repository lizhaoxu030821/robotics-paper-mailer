from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import dataclasses
import datetime
import email.message
import email.utils
import hashlib
import html
import http.client
import importlib.util
import json
import mimetypes
import os
import queue
import re
import smtplib
import ssl
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree
from nacl.public import PublicKey, SealedBox
from pathlib import Path
import tkinter as tk
from tkinter import BooleanVar, Canvas, Tk, StringVar, Text, Toplevel, messagebox, ttk


APP_NAME = "机器人论文云端助手"
APP_VERSION = "1.3.3"
UPDATE_REPOSITORY = "lizhaoxu030821/robotics-paper-mailer"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
UPDATE_ASSET_NAME = "robotics-paper-mailer.exe"
DEFAULT_SETTINGS = {
    "owner": "lizhaoxu030821",
    "repository": "robotics-paper-mailer",
    "workflow": "daily-paper.yml",
    "schedule": "每天 09:00（北京时间，由 GitHub Actions 触发）",
    "recipient": "2365318481@qq.com",
    # Public identifier of the user's GitHub OAuth App. It is not a secret.
    "github_oauth_client_id": "Ov23liStnNMd1qYsoqRR",
}
TOPICS = {
    "motion_control": ("机器人运动控制", "轨迹优化、动力学控制、稳定性与鲁棒控制"),
    "legged_humanoid": ("腿足与人形机器人", "双足、四足、步态与接触动力学"),
    "manipulation": ("机械臂与操作控制", "抓取、接触操作与移动操作"),
    "reinforcement_learning": ("强化学习控制", "策略学习、模仿学习、sim-to-real"),
    "mpc": ("模型预测控制 MPC", "在线优化、约束控制与预测规划"),
    "whole_body_control": ("全身控制 WBC", "多接触协调、任务优先级与人形控制"),
}
TOPIC_DEFAULT_RULES = {
    "motion_control": {"queries": ["cat:cs.RO AND all:control", "cat:eess.SY AND all:robot"], "keywords": {"motion control": 8, "robot control": 8, "trajectory optimization": 7}},
    "legged_humanoid": {"queries": ["cat:cs.RO AND all:locomotion", "cat:cs.RO AND all:humanoid"], "keywords": {"locomotion": 10, "legged": 10, "humanoid": 10, "quadruped": 9, "biped": 9}},
    "manipulation": {"queries": ["cat:cs.RO AND all:manipulation"], "keywords": {"manipulation": 8, "loco-manipulation": 12}},
    "reinforcement_learning": {"queries": ["cat:cs.RO AND all:reinforcement"], "keywords": {"reinforcement learning": 9, "rl": 5, "policy": 4, "sim-to-real": 7}},
    "mpc": {"queries": ["cat:cs.RO AND all:\"model predictive control\""], "keywords": {"mpc": 11, "model predictive control": 11}},
    "whole_body_control": {"queries": ["cat:cs.RO AND all:\"whole body\""], "keywords": {"whole-body": 12, "whole body": 12}},
}
DEFAULT_TOPIC_CONFIG = {
    "version": 1,
    "selected_topics": list(TOPICS),
    "custom_queries": [],
    "custom_keywords": {},
    "excluded_keywords": [],
    "papers_per_day": 1,
    "max_attachment_mb": 18,
    "weekday_topics": {},
    "weekly_rotation_order": [],
    "topic_overrides": {},
}


def app_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    directory = base / "CloudRoboticsPaperMailer"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


SETTINGS_PATH = app_data_dir() / "settings.json"
LOCAL_HISTORY_PATH = app_data_dir() / "data" / "sent_papers.json"
TOPIC_CONFIG_PATH = app_data_dir() / "paper_topics.json"
GITHUB_AUTH_PATH = app_data_dir() / "github_auth.json"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def load_settings() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()
    return {key: str(saved.get(key, value)) for key, value in DEFAULT_SETTINGS.items()}


def save_settings(settings: dict[str, str]) -> None:
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _data_blob(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def protect_for_current_windows_user(value: str) -> str:
    """Encrypt a GitHub token with Windows DPAPI for the current Windows user."""
    if os.name != "nt":
        raise RuntimeError("GitHub 登录凭据只能在 Windows 版软件中保存。")
    source, source_buffer = _data_blob(value.encode("utf-8"))
    result = _DataBlob()
    crypt_protect = ctypes.windll.crypt32.CryptProtectData
    crypt_protect.argtypes = [ctypes.POINTER(_DataBlob), ctypes.wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    crypt_protect.restype = ctypes.wintypes.BOOL
    if not crypt_protect(ctypes.byref(source), "Cloud Robotics Paper Mailer", None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return base64.b64encode(ctypes.string_at(result.pbData, result.cbData)).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def unprotect_for_current_windows_user(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("GitHub 登录凭据只能在 Windows 版软件中读取。")
    try:
        protected = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("GitHub 登录凭据格式无效。") from exc
    source, source_buffer = _data_blob(protected)
    result = _DataBlob()
    crypt_unprotect = ctypes.windll.crypt32.CryptUnprotectData
    crypt_unprotect.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.wintypes.LPWSTR), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.POINTER(_DataBlob)]
    crypt_unprotect.restype = ctypes.wintypes.BOOL
    if not crypt_unprotect(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.pbData, result.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def load_topic_settings() -> dict[str, object]:
    config = json.loads(json.dumps(DEFAULT_TOPIC_CONFIG))
    if not TOPIC_CONFIG_PATH.exists():
        return config
    try:
        saved = json.loads(TOPIC_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config
    if not isinstance(saved, dict):
        return config
    config.update({key: value for key, value in saved.items() if key in config})
    return config


def save_topic_settings(config: dict[str, object]) -> None:
    TOPIC_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_sender_module():
    script_path = resource_path("scripts/send_daily_robotics_paper.py")
    spec = importlib.util.spec_from_file_location("daily_robotics_paper", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载论文发送脚本。")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PaperMailerApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.topic_config = load_topic_settings()
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._oauth_status: StringVar | None = None
        self._oauth_code: StringVar | None = None
        self._oauth_dialog: Toplevel | None = None
        self._oauth_cancel = threading.Event()
        self._post_auth_action: str | None = None
        self.github_profile: dict[str, str] = {}
        self.github_account_text = StringVar(value="登录 GitHub")
        self.github_account_button: tk.Button | None = None
        self.github_avatar_image: tk.PhotoImage | None = None
        self._open_profile_after_refresh = False
        self._open_cloud_setup_after_profile = False
        self._update_check_manual = False
        self._update_check_running = False
        self._pending_update: dict[str, object] = {}
        self.status = StringVar(value="就绪。云端定时任务独立运行，不需要电脑开机。")
        self.local_env_status = StringVar()
        self.root.title(APP_NAME)
        self.root.geometry("1100x790")
        self.root.minsize(960, 680)
        self._configure_style()
        self._build_ui()
        self.refresh_status()
        self._refresh_github_profile()
        self.root.after(200, self.poll_events)
        self.root.after(2500, self.check_for_updates)

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        self.root.configure(bg="#edf3f1")
        style.configure("TFrame", background="#edf3f1")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#edf3f1", foreground="#173a36", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", background="#edf3f1", foreground="#123d37", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background="#edf3f1", foreground="#50726b", font=("Microsoft YaHei UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#123d37", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("CardText.TLabel", background="#ffffff", foreground="#45625d", font=("Microsoft YaHei UI", 10))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="#ffffff", background="#0b7a64", padding=(14, 9))
        style.map("Accent.TButton", background=[("active", "#086452")])
        style.configure("Soft.TButton", font=("Microsoft YaHei UI", 10), foreground="#17453f", background="#dcece7", padding=(12, 8))
        style.map("Soft.TButton", background=[("active", "#c9e2d9")])
        style.configure("TNotebook", background="#edf3f1", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=(20, 10), background="#dce9e5", foreground="#45625d")
        style.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#0b7a64")])

    def _card(self, parent: ttk.Frame, title: str, text: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text=text, style="CardText.TLabel", justify="left", wraplength=430).pack(anchor="w", pady=(8, 0))
        return card

    def _enable_minimize_button(self, dialog: Toplevel) -> None:
        """Restore the Windows minimize button while keeping popups non-resizable."""
        if os.name != "nt":
            return

        def apply_style() -> None:
            try:
                user32 = ctypes.windll.user32
                style = user32.GetWindowLongW(dialog.winfo_id(), -16)
                user32.SetWindowLongW(dialog.winfo_id(), -16, style | 0x00020000 | 0x00080000)
                user32.SetWindowPos(dialog.winfo_id(), None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
            except (AttributeError, tk.TclError):
                pass

        dialog.after(0, apply_style)

    def _show_popup(self, title: str, message: str, *, kind: str = "info", choices: bool = False, parent: Toplevel | None = None) -> bool:
        dialog = Toplevel(parent or self.root)
        dialog.title(title)
        dialog.transient(parent or self.root)
        dialog.resizable(False, False)
        self._enable_minimize_button(dialog)
        result = False
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        icon = {"info": "i", "warning": "!", "error": "x", "question": "?"}.get(kind, "i")
        icon_label = tk.Label(frame, text=icon, width=2, bg="#0b7a64" if kind in {"info", "question"} else "#bd4b43", fg="#ffffff", font=("Segoe UI", 18, "bold"), padx=7, pady=5)
        icon_label.pack(side="left", anchor="n", padx=(0, 14))
        content = ttk.Frame(frame, style="Card.TFrame")
        content.pack(side="left", fill="both", expand=True)
        ttk.Label(content, text=message, style="CardText.TLabel", justify="left", wraplength=480).pack(anchor="w")
        buttons = ttk.Frame(content, style="Card.TFrame")
        buttons.pack(anchor="e", pady=(18, 0))

        def close(value: bool) -> None:
            nonlocal result
            result = value
            dialog.destroy()

        if choices:
            ttk.Button(buttons, text="否", style="Soft.TButton", command=lambda: close(False)).pack(side="right")
            ttk.Button(buttons, text="是", style="Accent.TButton", command=lambda: close(True)).pack(side="right", padx=(0, 9))
        else:
            ttk.Button(buttons, text="确定", style="Accent.TButton", command=lambda: close(True)).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.wait_window()
        return result

    def _build_ui(self) -> None:
        header = ttk.Frame(self.root, padding=(38, 28, 38, 12))
        header.pack(fill="x")
        title_row = ttk.Frame(header)
        title_row.pack(fill="x")
        ttk.Label(title_row, text=APP_NAME, style="Title.TLabel").pack(side="left")
        self.github_account_button = tk.Button(
            title_row,
            textvariable=self.github_account_text,
            command=self.open_github_account,
            bg="#dcece7",
            activebackground="#c9e2d9",
            fg="#17453f",
            relief="flat",
            cursor="hand2",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=12,
            pady=6,
            compound="left",
        )
        self.github_account_button.pack(side="right", pady=(4, 0))
        ttk.Label(
            header,
            text="每天获取机器人运动控制前沿论文，邮件发送并同步到 Zotero。",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        notebook = ttk.Notebook(self.root)
        self.notebook = notebook
        notebook.pack(fill="both", expand=True, padx=38, pady=(4, 16))
        home = ttk.Frame(notebook, padding=20)
        topics = ttk.Frame(notebook, padding=20)
        history = ttk.Frame(notebook, padding=20)
        settings = ttk.Frame(notebook, padding=20)
        guide = ttk.Frame(notebook, padding=20)
        extensions = ttk.Frame(notebook, padding=20)
        notebook.add(home, text="总览")
        notebook.add(topics, text="推送主题")
        notebook.add(history, text="本地测试历史")
        notebook.add(settings, text="项目设置")
        notebook.add(guide, text="使用指南")
        notebook.add(extensions, text="扩展中心")
        self.topics_tab = topics
        self._build_home(home)
        self._build_topics(topics)
        self._build_history(history)
        self._build_settings(settings)
        self._build_guide(guide)
        self._build_extensions(extensions)

        footer = ttk.Frame(self.root, padding=(38, 0, 38, 20))
        footer.pack(fill="x")
        ttk.Label(footer, textvariable=self.status, style="Subtitle.TLabel").pack(anchor="w")

    def _build_home(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        cloud = self._card(
            parent,
            "云端自动发送",
            "定时器：" + self.settings["schedule"] + "\n执行链路：GitHub Actions → QQ 邮箱 / Zotero",
        )
        cloud.grid(row=0, column=0, sticky="nsew", padx=(0, 9), pady=(0, 9))
        ttk.Button(cloud, text="立即触发一次云端任务", style="Accent.TButton", command=self.trigger_cloud).pack(anchor="w", pady=(16, 0))
        ttk.Button(cloud, text="一键配置我的云端", style="Soft.TButton", command=self.open_cloud_setup).pack(anchor="w", pady=(9, 0))
        ttk.Button(cloud, text="打开 GitHub Actions", style="Soft.TButton", command=self.open_actions).pack(anchor="w", pady=(9, 0))

        local = self._card(
            parent,
            "本地测试",
            "本地发送用于验证 SMTP、论文检索和 Zotero，同一套云端逻辑会在电脑上直接运行。",
        )
        local.grid(row=0, column=1, sticky="nsew", padx=(9, 0), pady=(0, 9))
        ttk.Label(local, textvariable=self.local_env_status, style="CardText.TLabel", wraplength=420).pack(anchor="w", pady=(12, 0))
        buttons = ttk.Frame(local, style="Card.TFrame")
        buttons.pack(anchor="w", pady=(16, 0))
        ttk.Button(buttons, text="本地发送测试", style="Accent.TButton", command=self.run_local_test).pack(side="left")
        ttk.Button(buttons, text="检查环境", style="Soft.TButton", command=self.refresh_status).pack(side="left", padx=(9, 0))

        services = self._card(
            parent,
            "服务入口",
            "这些入口用于查看云端运行状态、修改定时规则，以及确认 Zotero 中的归档结果。",
        )
        services.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(9, 0))
        service_buttons = ttk.Frame(services, style="Card.TFrame")
        service_buttons.pack(anchor="w", pady=(16, 0))
        ttk.Button(service_buttons, text="打开 GitHub Actions", style="Soft.TButton", command=self.open_actions).pack(side="left")
        ttk.Button(service_buttons, text="打开 Zotero 网页库", style="Soft.TButton", command=lambda: webbrowser.open("https://www.zotero.org")).pack(side="left", padx=(9, 0))
        ttk.Button(service_buttons, text="打开项目文件夹", style="Soft.TButton", command=lambda: os.startfile(app_data_dir())).pack(side="left", padx=(9, 0))
        ttk.Button(service_buttons, text=f"检查更新 v{APP_VERSION}", style="Soft.TButton", command=lambda: self.check_for_updates(manual=True)).pack(side="left", padx=(9, 0))

    def _build_topics(self, parent: ttk.Frame) -> None:
        canvas = Canvas(parent, bg="#edf3f1", highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas, padding=20)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_content(event) -> None:
            canvas.itemconfigure(content_window, width=event.width)

        def on_mouse_wheel(event) -> None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_content)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_mouse_wheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))
        self._build_topics_content(content)

    def _build_topics_content(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="论文主题与筛选规则", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text="保存后会立刻用于本地测试；点击“发布到云端”后，下一次定时任务也会使用相同设置。", style="Subtitle.TLabel").pack(anchor="w", pady=(6, 14))

        topic_card = ttk.Frame(parent, style="Card.TFrame", padding=20)
        topic_card.pack(fill="x")
        ttk.Label(topic_card, text="选择推送主题", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.topic_vars: dict[str, BooleanVar] = {}
        self.topic_tiles: dict[str, tuple[tk.Frame, tk.Checkbutton, tk.Label]] = {}
        selected_topics = self.topic_config.get("selected_topics", [])
        topic_overrides = self.topic_config.get("topic_overrides", {})
        for index, (topic_id, (label, description)) in enumerate(TOPICS.items()):
            override = topic_overrides.get(topic_id, {}) if isinstance(topic_overrides, dict) else {}
            display_label = override.get("label", label) if isinstance(override, dict) else label
            variable = BooleanVar(value=topic_id in selected_topics)
            self.topic_vars[topic_id] = variable
            cell = tk.Frame(topic_card, bg="#f7fbf9", highlightthickness=1, cursor="hand2")
            cell.grid(row=1 + index // 2, column=index % 2, sticky="ew", padx=(0, 16) if index % 2 == 0 else (16, 0), pady=7)
            toggle = tk.Checkbutton(
                cell,
                text=display_label,
                variable=variable,
                command=lambda current_id=topic_id: self.select_topic(current_id),
                bg="#f7fbf9",
                activebackground="#e5f4ee",
                fg="#173a36",
                font=("Microsoft YaHei UI", 11, "bold"),
                anchor="w",
                cursor="hand2",
                relief="flat",
                highlightthickness=0,
            )
            toggle.pack(fill="x", padx=12, pady=(9, 2))
            detail = tk.Label(cell, text=description, bg="#f7fbf9", fg="#53726b", font=("Microsoft YaHei UI", 9), anchor="w", cursor="hand2")
            detail.pack(fill="x", padx=38, pady=(0, 9))
            for widget in (cell, detail):
                widget.bind("<Button-1>", lambda _event, current_id=topic_id: self.select_topic(current_id))
            self.topic_tiles[topic_id] = (cell, toggle, detail)
        topic_card.columnconfigure(0, weight=1)
        topic_card.columnconfigure(1, weight=1)

        editor = ttk.Frame(topic_card, style="Card.TFrame")
        editor.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        editor.columnconfigure(1, weight=1)
        ttk.Label(editor, text="主题编辑器", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(editor, text="选择一个主题后，可直接修改名称、arXiv 查询和关键词权重。关键词格式为“关键词: 权重”。", style="CardText.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 12))
        self.topic_choice = StringVar(value=next(iter(TOPICS)))
        self.active_topic_label = StringVar()
        ttk.Label(editor, text="当前编辑主题", style="CardText.TLabel").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Label(editor, textvariable=self.active_topic_label, style="CardTitle.TLabel").grid(row=2, column=1, sticky="w", pady=5)
        self.topic_name = StringVar()
        ttk.Label(editor, text="主题名称", style="CardText.TLabel").grid(row=3, column=0, sticky="w", pady=5)
        ttk.Entry(editor, textvariable=self.topic_name, width=52).grid(row=3, column=1, sticky="ew", pady=5)
        ttk.Label(editor, text="主题 arXiv 查询", style="CardText.TLabel").grid(row=4, column=0, sticky="nw", pady=5)
        self.topic_queries_editor = Text(editor, height=4, font=("Consolas", 9), bg="#f5f9f7", relief="flat", padx=8, pady=8)
        self.topic_queries_editor.grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Label(editor, text="主题关键词与权重", style="CardText.TLabel").grid(row=5, column=0, sticky="nw", pady=5)
        self.topic_keywords_editor = Text(editor, height=5, font=("Consolas", 9), bg="#f5f9f7", relief="flat", padx=8, pady=8)
        self.topic_keywords_editor.grid(row=5, column=1, sticky="ew", pady=5)
        ttk.Button(editor, text="保存当前主题编辑", style="Soft.TButton", command=self.save_current_topic_editor).grid(row=6, column=1, sticky="w", pady=(8, 0))
        self._load_topic_editor()

        tuning = ttk.Frame(parent, style="Card.TFrame", padding=20)
        tuning.pack(fill="both", expand=True, pady=(14, 0))
        tuning.columnconfigure(0, weight=1)
        tuning.columnconfigure(1, weight=1)
        ttk.Label(tuning, text="高级筛选与投递", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        left = ttk.Frame(tuning, style="Card.TFrame")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 14), pady=(12, 0))
        ttk.Label(left, text="自定义 arXiv 查询（每行一条）", style="CardText.TLabel").pack(anchor="w")
        self.custom_queries_text = Text(left, height=5, font=("Consolas", 9), bg="#f5f9f7", relief="flat", padx=8, pady=8)
        self.custom_queries_text.pack(fill="x", pady=(5, 10))
        self.custom_queries_text.insert("1.0", "\n".join(self.topic_config.get("custom_queries", [])))
        ttk.Label(left, text="示例：cat:cs.RO AND all:diffusion", style="CardText.TLabel").pack(anchor="w")
        ttk.Label(left, text="自定义关键词（每行“关键词: 权重”）", style="CardText.TLabel").pack(anchor="w", pady=(12, 0))
        self.custom_keywords_text = Text(left, height=5, font=("Consolas", 9), bg="#f5f9f7", relief="flat", padx=8, pady=8)
        self.custom_keywords_text.pack(fill="x", pady=(5, 0))
        custom_keywords = self.topic_config.get("custom_keywords", {})
        self.custom_keywords_text.insert("1.0", "\n".join(f"{key}: {value}" for key, value in custom_keywords.items()))

        right = ttk.Frame(tuning, style="Card.TFrame")
        right.grid(row=1, column=1, sticky="nsew", padx=(14, 0), pady=(12, 0))
        ttk.Label(right, text="排除关键词（每行一条，命中后不推送）", style="CardText.TLabel").pack(anchor="w")
        self.excluded_keywords_text = Text(right, height=4, font=("Consolas", 9), bg="#f5f9f7", relief="flat", padx=8, pady=8)
        self.excluded_keywords_text.pack(fill="x", pady=(5, 10))
        self.excluded_keywords_text.insert("1.0", "\n".join(self.topic_config.get("excluded_keywords", [])))

        delivery = tk.Frame(right, bg="#ffffff")
        delivery.pack(fill="x")
        tk.Label(delivery, text="每日篇数", bg="#ffffff", fg="#45625d", font=("Microsoft YaHei UI", 10)).grid(row=0, column=0, sticky="w", pady=5)
        self.paper_count = StringVar(value=str(self.topic_config.get("papers_per_day", 1)))
        tk.Entry(delivery, textvariable=self.paper_count, width=6, justify="center", font=("Microsoft YaHei UI", 10), relief="solid", bd=1).grid(row=0, column=1, sticky="w", padx=(12, 8))
        tk.Label(delivery, text="篇 / 天", bg="#ffffff", fg="#78918a", font=("Microsoft YaHei UI", 9)).grid(row=0, column=2, sticky="w")
        tk.Label(delivery, text="PDF 附件上限", bg="#ffffff", fg="#45625d", font=("Microsoft YaHei UI", 10)).grid(row=1, column=0, sticky="w", pady=5)
        self.attachment_limit = StringVar(value=str(self.topic_config.get("max_attachment_mb", 18)))
        tk.Entry(delivery, textvariable=self.attachment_limit, width=6, justify="center", font=("Microsoft YaHei UI", 10), relief="solid", bd=1).grid(row=1, column=1, sticky="w", padx=(12, 8))
        tk.Label(delivery, text="MB", bg="#ffffff", fg="#78918a", font=("Microsoft YaHei UI", 9)).grid(row=1, column=2, sticky="w")

        ttk.Label(right, text="每周主题轮换", style="CardTitle.TLabel").pack(anchor="w", pady=(18, 0))
        selected_ids = [topic_id for topic_id, variable in self.topic_vars.items() if variable.get()]
        saved_order = self.topic_config.get("weekly_rotation_order", [])
        self.rotation_order = [topic_id for topic_id in saved_order if topic_id in selected_ids] if isinstance(saved_order, list) else []
        self.rotation_order += [topic_id for topic_id in selected_ids if topic_id not in self.rotation_order]
        ttk.Label(right, text="单独打开编排器后，可拖动主题方块决定周一到周日的推送顺序。", style="CardText.TLabel", wraplength=480).pack(anchor="w", pady=(4, 8))
        self.rotation_summary = StringVar()
        ttk.Label(right, textvariable=self.rotation_summary, style="CardText.TLabel", wraplength=480).pack(anchor="w", pady=(0, 8))
        ttk.Button(right, text="打开每周轮换编排器", style="Accent.TButton", command=self.open_rotation_planner).pack(anchor="w")
        self._update_rotation_summary()

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="保存到软件", style="Soft.TButton", command=self.save_topics).pack(side="left")
        ttk.Button(buttons, text="发布到 GitHub 云端", style="Accent.TButton", command=self.publish_topics).pack(side="left", padx=(10, 0))
        ttk.Button(buttons, text="打开配置文件夹", style="Soft.TButton", command=lambda: os.startfile(app_data_dir())).pack(side="right")

    def _build_guide(self, parent: ttk.Frame) -> None:
        canvas = Canvas(parent, bg="#edf3f1", highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas, padding=(8, 6, 20, 24))
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        ttk.Label(content, text="首次使用指南", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            content,
            text="正常情况下，只需准备第三方服务提供的凭据，其余 GitHub 云端配置由软件自动完成。",
            style="Subtitle.TLabel",
            wraplength=850,
        ).pack(anchor="w", pady=(6, 16))

        step1 = self._card(
            content,
            "第 1 步：准备 QQ 邮箱 SMTP 授权码（需要手动）",
            "进入 QQ 邮箱设置，开启 SMTP 服务并生成授权码。授权码不是 QQ 登录密码，软件和 GitHub Actions 使用它发送邮件。这个操作必须由邮箱本人在 QQ 邮箱完成，软件不能替你生成。",
        )
        step1.pack(fill="x", pady=(0, 10))
        ttk.Button(step1, text="打开 QQ 邮箱", style="Soft.TButton", command=lambda: webbrowser.open("https://mail.qq.com")).pack(anchor="w", pady=(14, 0))

        step2 = self._card(
            content,
            "第 2 步：登录 GitHub（需要确认一次）",
            "点击软件右上角“登录 GitHub”，在 GitHub 官方页面输入设备授权码并同意授权。软件会记住本机加密登录状态，不需要创建 Fine-grained Token。",
        )
        step2.pack(fill="x", pady=10)
        ttk.Button(step2, text="登录或查看 GitHub 账户", style="Soft.TButton", command=self.open_github_account).pack(anchor="w", pady=(14, 0))

        step3 = self._card(
            content,
            "第 3 步：可选准备 Zotero",
            "如果希望论文自动进入 Zotero，请先在 Zotero 网页创建 API Key，并在 Zotero 中创建目标分类。记下 API Key、User ID 和分类名称。不使用 Zotero 时可以跳过这一步。",
        )
        step3.pack(fill="x", pady=10)
        zotero_buttons = ttk.Frame(step3, style="Card.TFrame")
        zotero_buttons.pack(anchor="w", pady=(14, 0))
        ttk.Button(zotero_buttons, text="创建 Zotero API Key", style="Soft.TButton", command=lambda: webbrowser.open("https://www.zotero.org/settings/keys")).pack(side="left")
        ttk.Button(zotero_buttons, text="打开 Zotero 网页库", style="Soft.TButton", command=lambda: webbrowser.open("https://www.zotero.org")).pack(side="left", padx=(9, 0))

        step4 = self._card(
            content,
            "第 4 步：在软件内完成云端配置（自动）",
            "点击下面按钮，填写仓库名、QQ 邮箱、SMTP 授权码、收件邮箱、北京时间和可选的 Zotero 信息。点击完成后，软件会自动创建个人 GitHub 仓库、上传脚本、配置工作流、加密写入 Secrets、设置每日定时并启动首次测试。",
        )
        step4.pack(fill="x", pady=10)
        ttk.Button(step4, text="一键配置我的云端", style="Accent.TButton", command=self.open_cloud_setup).pack(anchor="w", pady=(14, 0))

        automatic = self._card(
            content,
            "软件自动完成的内容",
            "创建或复用用户自己的 GitHub 仓库；上传论文脚本和主题配置；创建 GitHub Actions 工作流；把北京时间转换成 UTC 定时规则；加密上传 QQ SMTP 与 Zotero Secrets；触发首次测试；后续将主题修改同步到用户自己的仓库。",
        )
        automatic.pack(fill="x", pady=10)

        manual = self._card(
            content,
            "仍需用户手动完成的内容",
            "QQ 邮箱开启 SMTP 并生成授权码；首次 GitHub 官方授权确认；可选创建 Zotero API Key 和分类；收到首次测试邮件后确认结果。GitHub Actions 定时任务可能因平台排队延迟，不保证严格在整点执行。",
        )
        manual.pack(fill="x", pady=10)

        verify = self._card(
            content,
            "第 5 步：检查是否成功",
            "完成配置后，等待首次测试邮件。也可以打开 GitHub Actions 查看绿色成功标记，再到 Zotero 目标分类确认文献和 PDF。若失败，Actions 日志会显示具体步骤。",
        )
        verify.pack(fill="x", pady=10)
        verify_buttons = ttk.Frame(verify, style="Card.TFrame")
        verify_buttons.pack(anchor="w", pady=(14, 0))
        ttk.Button(verify_buttons, text="打开 GitHub Actions", style="Soft.TButton", command=self.open_actions).pack(side="left")
        ttk.Button(verify_buttons, text="立即触发测试", style="Accent.TButton", command=self.trigger_cloud).pack(side="left", padx=(9, 0))

        ttk.Separator(content).pack(fill="x", pady=24)
        ttk.Label(content, text="配置完成后：定制个性化文献推送", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            content,
            text="以下设置都在“推送主题”页面完成。修改后先保存，再发布到 GitHub 云端，下一次定时任务才会采用新规则。",
            style="Subtitle.TLabel",
            wraplength=850,
        ).pack(anchor="w", pady=(6, 16))
        ttk.Button(content, text="打开推送主题页面", style="Accent.TButton", command=self.open_topics_tab).pack(anchor="w", pady=(0, 12))

        choose_topics = self._card(
            content,
            "1. 选择感兴趣的研究方向",
            "勾选需要的主题，例如腿足与人形机器人、机械臂控制、强化学习控制、MPC 或全身控制。取消不关心的主题，可以减少无关论文。至少保留一个主题。",
        )
        choose_topics.pack(fill="x", pady=10)

        edit_topic = self._card(
            content,
            "2. 修改主题名称、arXiv 查询式和关键词权重",
            "点击主题方块后，在下方编辑器修改规则。arXiv 查询式决定从哪里寻找候选论文；关键词权重决定候选论文的排序优先级。权重越高，标题或摘要命中该词时得分越高。例：humanoid: 12、whole-body: 10、sim-to-real: 8。权重不是百分比，也不会保证每天一定出现该关键词。",
        )
        edit_topic.pack(fill="x", pady=10)

        custom_rules = self._card(
            content,
            "3. 添加自定义查询、偏好词和排除词",
            "自定义 arXiv 查询每行一条，例如 cat:cs.RO AND all:diffusion。自定义关键词使用“关键词: 权重”格式，例如 dexterous manipulation: 12。排除关键词每行一个，例如 medical、surgery；论文标题或摘要命中排除词后不会被推送。规则建议先少量添加，过多排除词可能导致没有合适论文。",
        )
        custom_rules.pack(fill="x", pady=10)

        delivery_rules = self._card(
            content,
            "4. 设置每日篇数和 PDF 附件上限",
            "每日篇数支持 1 到 5 篇，每篇会单独发送邮件。PDF 附件上限用于避免邮箱拒收大文件；超过上限时邮件仍会提供论文和 PDF 链接。QQ 邮箱建议保持默认 18 MB，确认邮箱限制后再调整。",
        )
        delivery_rules.pack(fill="x", pady=10)

        weekly_rotation = self._card(
            content,
            "5. 设置每周主题轮换",
            "打开每周轮换编排器，纵向拖动主题顺序。第 1 个主题对应周一，第 2 个对应周二，依次到周日；主题不足 7 个时会循环使用。这样可以让不同日期关注不同方向，避免每天所有主题混在一起竞争。",
        )
        weekly_rotation.pack(fill="x", pady=10)

        publish_rules = self._card(
            content,
            "6. 保存并同步到云端",
            "点击“保存到软件”只会更新本机规则；随后在提示中选择“是”，或直接点击“发布到 GitHub 云端”，软件才会把主题配置同步到你的 GitHub 仓库。看到“主题设置已发布到 GitHub”后，下一次定时推送会使用新规则。",
        )
        publish_rules.pack(fill="x", pady=10)

        test_rules = self._card(
            content,
            "7. 立即测试个性化规则",
            "发布完成后点击“立即触发一次云端任务”。在 GitHub Actions 中等待运行成功，再检查邮箱标题、论文方向和 Zotero 分类。若结果偏离预期，优先调整主题勾选、关键词权重和排除词，然后重新发布测试。",
        )
        test_rules.pack(fill="x", pady=10)

        recommendations = self._card(
            content,
            "推荐的起步配置",
            "先选择 2 到 3 个最关心的主题，每日发送 1 篇，保留默认 PDF 上限；为核心方向设置 10 到 12 的权重，次要方向设置 5 到 8；运行一周后根据收到的论文逐步增加排除词。不要一开始堆很多查询和关键词，否则很难判断是哪条规则影响了结果。",
        )
        recommendations.pack(fill="x", pady=10)

    def open_topics_tab(self) -> None:
        self.notebook.select(self.topics_tab)

    def _build_extensions(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="扩展中心", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text="这里列出当前软件可配置的能力，以及需要额外服务后才能启用的二次开发方向。", style="Subtitle.TLabel").pack(anchor="w", pady=(6, 14))
        extension_buttons = ttk.Frame(parent)
        extension_buttons.pack(fill="x", pady=(0, 12))
        ttk.Button(extension_buttons, text="打开完整功能说明", style="Soft.TButton", command=self.open_features_guide).pack(side="left")
        ttk.Button(extension_buttons, text="版本发布与自动更新说明", style="Soft.TButton", command=self.open_releasing_guide).pack(side="left", padx=(9, 0))
        ttk.Button(extension_buttons, text="未来开发路线图", style="Soft.TButton", command=self.open_roadmap_guide).pack(side="left", padx=(9, 0))
        ttk.Button(extension_buttons, text="版本更新记录", style="Soft.TButton", command=self.open_changelog_guide).pack(side="left", padx=(9, 0))
        content = Text(parent, height=26, font=("Microsoft YaHei UI", 10), bg="#ffffff", fg="#173a36", relief="flat", padx=20, pady=18, wrap="word")
        content.pack(fill="both", expand=True)
        content.insert("1.0", """功能概览\n\n• 已实现：主题与权重配置、arXiv 检索、邮件/PDF、Zotero 同步、GitHub 登录、一键创建并配置用户个人云端仓库、GitHub Actions 定时、每周主题轮换和软件自动更新。\n• 用户需要提供：QQ SMTP 授权码；Zotero API Key、User ID 和分类名称为可选项。\n• 近期重点：配置诊断、失败重试、日志导出、论文质量反馈与多数据源检索。\n• 中长期：中文深度摘要、周报、后台统计、正式安装签名和多渠道推送。\n\n可通过上方按钮查看完整功能说明、发布说明、开发路线图和版本更新记录。\n""")
        content.configure(state="disabled")

    def open_features_guide(self) -> None:
        guide_path = resource_path("FEATURES.md")
        if not guide_path.exists():
            self._show_popup(APP_NAME, "未找到功能说明文件。请重新安装或使用最新版软件。", kind="error")
            return
        os.startfile(guide_path)

    def open_releasing_guide(self) -> None:
        guide_path = resource_path("RELEASING.md")
        if not guide_path.exists():
            self._show_popup(APP_NAME, "未找到版本发布说明文件。请重新安装或使用最新版软件。", kind="error")
            return
        os.startfile(guide_path)

    def open_roadmap_guide(self) -> None:
        guide_path = resource_path("ROADMAP.md")
        if not guide_path.exists():
            self._show_popup(APP_NAME, "未找到开发路线图。请重新安装或使用最新版软件。", kind="error")
            return
        os.startfile(guide_path)

    def open_changelog_guide(self) -> None:
        guide_path = resource_path("CHANGELOG.md")
        if not guide_path.exists():
            self._show_popup(APP_NAME, "未找到版本更新记录。请重新安装或使用最新版软件。", kind="error")
            return
        os.startfile(guide_path)

    def _build_history(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent)
        top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text="本地发送历史", style="CardTitle.TLabel").pack(side="left")
        ttk.Button(top, text="刷新", style="Soft.TButton", command=self.refresh_history).pack(side="right")
        ttk.Label(
            parent,
            text="云端实际去重历史保存在 GitHub 仓库的 data/sent_papers.json。本页显示从本软件发起的本地测试记录。",
            style="Subtitle.TLabel",
            wraplength=850,
        ).pack(anchor="w", pady=(0, 12))
        self.history_text = Text(parent, height=24, font=("Consolas", 10), bg="#ffffff", fg="#173a36", relief="flat", padx=16, pady=14)
        self.history_text.pack(fill="both", expand=True)
        self.refresh_history()

    def _build_settings(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="项目设置", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text="仅保存仓库地址、时间说明和收件人等公开配置；授权码和 Token 不会保存在软件中。", style="Subtitle.TLabel").pack(anchor="w", pady=(6, 18))
        form = ttk.Frame(parent, style="Card.TFrame", padding=22)
        form.pack(fill="x")
        self.fields: dict[str, StringVar] = {}
        labels = [("owner", "GitHub 用户名"), ("repository", "仓库名称"), ("workflow", "工作流文件"), ("schedule", "定时说明"), ("recipient", "默认收件邮箱")]
        for row, (key, label) in enumerate(labels):
            ttk.Label(form, text=label, style="CardText.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 20), pady=8)
            value = StringVar(value=self.settings[key])
            self.fields[key] = value
            ttk.Entry(form, textvariable=value, width=55).grid(row=row, column=1, sticky="ew", pady=8)
        form.columnconfigure(1, weight=1)
        ttk.Button(parent, text="保存公开配置", style="Accent.TButton", command=self.save_public_settings).pack(anchor="w", pady=(16, 0))

    def _topic_rule(self, topic_id: str) -> dict[str, object]:
        default = TOPIC_DEFAULT_RULES[topic_id]
        overrides = self.topic_config.get("topic_overrides", {})
        override = overrides.get(topic_id, {}) if isinstance(overrides, dict) else {}
        return {
            "label": override.get("label", TOPICS[topic_id][0]) if isinstance(override, dict) else TOPICS[topic_id][0],
            "queries": override.get("queries", default["queries"]) if isinstance(override, dict) else default["queries"],
            "keywords": override.get("keywords", default["keywords"]) if isinstance(override, dict) else default["keywords"],
        }

    def select_topic(self, topic_id: str) -> None:
        self.topic_choice.set(topic_id)
        self._load_topic_editor()
        if hasattr(self, "rotation_order"):
            if self.topic_vars[topic_id].get() and topic_id not in self.rotation_order:
                self.rotation_order.append(topic_id)
            elif not self.topic_vars[topic_id].get() and topic_id in self.rotation_order:
                self.rotation_order.remove(topic_id)
            self._update_rotation_summary()
        if hasattr(self, "rotation_canvas") and self.rotation_canvas.winfo_exists():
            self._render_rotation_board()

    def _update_rotation_summary(self) -> None:
        if not hasattr(self, "rotation_summary"):
            return
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        if not self.rotation_order:
            self.rotation_summary.set("尚未选择用于轮换的主题。")
            return
        items = []
        for index, day in enumerate(days):
            topic_id = self.rotation_order[index % len(self.rotation_order)]
            items.append(f"{day} {self._topic_rule(topic_id)['label']}")
        self.rotation_summary.set(" · ".join(items))

    def open_rotation_planner(self) -> None:
        if hasattr(self, "rotation_dialog") and self.rotation_dialog.winfo_exists():
            self.rotation_dialog.focus_set()
            return
        dialog = Toplevel(self.root)
        self._enable_minimize_button(dialog)
        dialog.title("每周主题轮换编排器")
        dialog.geometry("920x610")
        dialog.minsize(760, 500)
        dialog.transient(self.root)
        dialog.configure(bg="#edf3f1")
        self.rotation_dialog = dialog
        header = ttk.Frame(dialog, padding=(30, 26, 30, 10))
        header.pack(fill="x")
        ttk.Label(header, text="每周主题轮换编排器", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="拖动方块调整顺序。第 1 个主题对应周一，第 2 个对应周二，主题不足七个时会循环使用。", style="Subtitle.TLabel").pack(anchor="w", pady=(6, 0))
        board = ttk.Frame(dialog, style="Card.TFrame", padding=20)
        board.pack(fill="both", expand=True, padx=30, pady=12)
        planner_scrollbar = ttk.Scrollbar(board, orient="vertical")
        planner_scrollbar.pack(side="right", fill="y")
        self.rotation_canvas = tk.Canvas(board, bg="#edf6f2", highlightthickness=0, cursor="hand2", yscrollcommand=planner_scrollbar.set)
        self.rotation_canvas.pack(side="left", fill="both", expand=True)
        planner_scrollbar.configure(command=self.rotation_canvas.yview)
        self.rotation_canvas.bind("<Configure>", lambda _event: self._render_rotation_board())
        self.rotation_canvas.bind("<Enter>", lambda _event: self.rotation_canvas.bind_all("<MouseWheel>", self._scroll_rotation_board))
        self.rotation_canvas.bind("<Leave>", lambda _event: self.rotation_canvas.unbind_all("<MouseWheel>"))
        footer = ttk.Frame(dialog, padding=(30, 6, 30, 24))
        footer.pack(fill="x")
        ttk.Button(footer, text="完成编排", style="Accent.TButton", command=self.close_rotation_planner).pack(side="right")
        ttk.Button(footer, text="恢复主题默认顺序", style="Soft.TButton", command=self.reset_rotation_order).pack(side="right", padx=(0, 10))
        dialog.protocol("WM_DELETE_WINDOW", self.close_rotation_planner)
        self._render_rotation_board()

    def reset_rotation_order(self) -> None:
        self.rotation_order = [topic_id for topic_id, variable in self.topic_vars.items() if variable.get()]
        self._render_rotation_board()
        self._update_rotation_summary()

    def close_rotation_planner(self) -> None:
        self._update_rotation_summary()
        self.status.set("每周主题轮换顺序已暂存。点击“保存到软件”后写入配置。")
        if hasattr(self, "rotation_dialog") and self.rotation_dialog.winfo_exists():
            self.rotation_dialog.destroy()
        if hasattr(self, "rotation_canvas"):
            self.rotation_canvas.unbind_all("<MouseWheel>")
            del self.rotation_canvas

    def _scroll_rotation_board(self, event) -> None:
        if hasattr(self, "rotation_canvas"):
            self.rotation_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _render_rotation_board(self) -> None:
        if not hasattr(self, "rotation_canvas"):
            return
        canvas = self.rotation_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 700)
        gap, top, card_height = 12, 24, 48
        card_x1, card_x2 = 120, width - 32
        self.rotation_slots: dict[str, tuple[float, float, float, float]] = {}
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for index, day in enumerate(day_names):
            y1 = top + index * (card_height + gap)
            canvas.create_text(38, y1 + card_height / 2, text=day, anchor="w", fill="#0b7a64", font=("Microsoft YaHei UI", 10, "bold"))
            canvas.create_line(92, y1 + card_height / 2, 108, y1 + card_height / 2, fill="#9ccdbd", width=2)
        for index, topic_id in enumerate(self.rotation_order):
            x1, x2 = card_x1, card_x2
            y1 = top + index * (card_height + gap)
            y2 = y1 + card_height
            tag = f"rotation-{topic_id}"
            active = topic_id == self.topic_choice.get()
            fill = "#cfeee2" if active else "#ffffff"
            outline = "#0b7a64" if active else "#bcd9cd"
            canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=2 if active else 1, tags=(tag,))
            label = self._topic_rule(topic_id)["label"]
            canvas.create_text(x1 + 18, y1 + card_height / 2, text=label, anchor="w", fill="#173a36", font=("Microsoft YaHei UI", 11, "bold"), tags=(tag,))
            canvas.tag_bind(tag, "<ButtonPress-1>", lambda event, current_id=topic_id: self._start_rotation_drag(event, current_id))
            canvas.tag_bind(tag, "<B1-Motion>", self._drag_rotation_card)
            canvas.tag_bind(tag, "<ButtonRelease-1>", self._drop_rotation_card)
            self.rotation_slots[topic_id] = (x1, y1, x2, y2)
        if self.rotation_order and len(self.rotation_order) < len(day_names):
            repeat_day = day_names[len(self.rotation_order)]
            repeat_label = self._topic_rule(self.rotation_order[0])["label"]
            repeat_y = top + len(self.rotation_order) * (card_height + gap) + card_height / 2
            canvas.create_text(card_x1, repeat_y, text=f"{repeat_day} 起按顺序循环，下一项为“{repeat_label}”", anchor="w", fill="#69857d", font=("Microsoft YaHei UI", 9, "italic"))
        content_height = top + len(day_names) * (card_height + gap) + 24
        canvas.configure(scrollregion=(0, 0, width, content_height))

    def _start_rotation_drag(self, event, topic_id: str) -> None:
        self.rotation_drag_topic = topic_id
        self.rotation_drag_position = (event.x, event.y)
        self.rotation_drag_origin = (event.x, event.y)
        self.rotation_drag_moved = False
        self.rotation_canvas.tag_raise(f"rotation-{topic_id}")

    def _drag_rotation_card(self, event) -> None:
        if not hasattr(self, "rotation_drag_topic"):
            return
        previous_x, previous_y = self.rotation_drag_position
        if abs(event.x - self.rotation_drag_origin[0]) > 4 or abs(event.y - self.rotation_drag_origin[1]) > 4:
            self.rotation_drag_moved = True
        self.rotation_canvas.move(f"rotation-{self.rotation_drag_topic}", event.x - previous_x, event.y - previous_y)
        self.rotation_drag_position = (event.x, event.y)

    def _drop_rotation_card(self, event) -> None:
        if not hasattr(self, "rotation_drag_topic"):
            return
        topic_id = self.rotation_drag_topic
        if not self.rotation_drag_moved:
            del self.rotation_drag_topic
            self.select_topic(topic_id)
            return
        remaining = [current_id for current_id in self.rotation_order if current_id != topic_id]
        _, _, _, dragged_bottom = self.rotation_canvas.bbox(f"rotation-{topic_id}")
        target_index = 0
        for current_id in remaining:
            _, sibling_top, _, _ = self.rotation_slots[current_id]
            if dragged_bottom > sibling_top:
                target_index += 1
        remaining.insert(target_index, topic_id)
        self.rotation_order = remaining
        del self.rotation_drag_topic
        self._render_rotation_board()
        self._update_rotation_summary()

    def _refresh_topic_tiles(self) -> None:
        active_id = self.topic_choice.get()
        for topic_id, (cell, toggle, detail) in self.topic_tiles.items():
            if topic_id == active_id:
                background, border, foreground = "#d9f1e8", "#0b7a64", "#075e4d"
            elif self.topic_vars[topic_id].get():
                background, border, foreground = "#f4faf7", "#b9d8cb", "#173a36"
            else:
                background, border, foreground = "#ffffff", "#dde8e3", "#526c65"
            cell.configure(bg=background, highlightbackground=border, highlightcolor=border)
            toggle.configure(bg=background, activebackground=background, fg=foreground)
            detail.configure(bg=background, fg="#48675f" if topic_id == active_id else "#66827b")

    def _load_topic_editor(self) -> None:
        topic_id = self.topic_choice.get()
        rule = self._topic_rule(topic_id)
        self.active_topic_label.set(f"{rule['label']}  ·  {topic_id}")
        self.topic_name.set(str(rule["label"]))
        self.topic_queries_editor.delete("1.0", "end")
        self.topic_queries_editor.insert("1.0", "\n".join(rule["queries"]))
        self.topic_keywords_editor.delete("1.0", "end")
        self.topic_keywords_editor.insert("1.0", "\n".join(f"{key}: {value}" for key, value in rule["keywords"].items()))
        self._refresh_topic_tiles()

    def _parse_weighted_keywords(self, text: str) -> dict[str, int]:
        keywords: dict[str, int] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            name, separator, weight = line.rpartition(":")
            if not separator:
                name, weight = line, "7"
            try:
                keywords[name.strip()] = max(1, min(30, int(weight.strip())))
            except ValueError as exc:
                raise ValueError(f"关键词权重格式不正确：{line}") from exc
        return keywords

    def _save_topic_override(self, notify: bool) -> None:
        topic_id = self.topic_choice.get()
        label = self.topic_name.get().strip()
        queries = [line.strip() for line in self.topic_queries_editor.get("1.0", "end").splitlines() if line.strip()]
        keywords = self._parse_weighted_keywords(self.topic_keywords_editor.get("1.0", "end"))
        if not label or not queries or not keywords:
            raise ValueError("主题名称、至少一条查询和至少一个关键词权重都不能为空。")
        overrides = self.topic_config.setdefault("topic_overrides", {})
        overrides[topic_id] = {"label": label, "queries": queries, "keywords": keywords}
        self.topic_tiles[topic_id][1].configure(text=label)
        self.active_topic_label.set(f"{label}  ·  {topic_id}")
        if notify:
            self.status.set(f"已暂存“{label}”的编辑。请再点击“保存到软件”或“发布到 GitHub 云端”。")
            self._show_popup(APP_NAME, "当前主题编辑已暂存。")

    def save_current_topic_editor(self) -> None:
        try:
            self._save_topic_override(notify=True)
        except ValueError as exc:
            self._show_popup(APP_NAME, str(exc), kind="warning")

    def _format_weekday_topics(self, value: object) -> str:
        if not isinstance(value, dict):
            return ""
        labels = {"0": "周一", "1": "周二", "2": "周三", "3": "周四", "4": "周五", "5": "周六", "6": "周日"}
        return "\n".join(f"{labels[key]}: {', '.join(topics)}" for key, topics in value.items() if key in labels and isinstance(topics, list))

    def _collect_topic_config(self) -> dict[str, object]:
        self._save_topic_override(notify=False)
        selected = [topic_id for topic_id, variable in self.topic_vars.items() if variable.get()]
        if not selected:
            raise ValueError("至少选择一个推送主题。")
        queries = [line.strip() for line in self.custom_queries_text.get("1.0", "end").splitlines() if line.strip()]
        keywords = self._parse_weighted_keywords(self.custom_keywords_text.get("1.0", "end"))
        excluded = [line.strip() for line in self.excluded_keywords_text.get("1.0", "end").splitlines() if line.strip()]
        try:
            paper_count = max(1, min(5, int(self.paper_count.get())))
            attachment_limit = max(1, min(25, int(self.attachment_limit.get())))
        except ValueError as exc:
            raise ValueError("每日篇数和 PDF 附件上限必须是数字。") from exc
        return {
            "version": 1,
            "selected_topics": selected,
            "custom_queries": queries,
            "custom_keywords": keywords,
            "excluded_keywords": excluded,
            "papers_per_day": paper_count,
            "max_attachment_mb": attachment_limit,
            "weekday_topics": {},
            "weekly_rotation_order": [topic_id for topic_id in self.rotation_order if topic_id in selected],
            "topic_overrides": self.topic_config.get("topic_overrides", {}),
        }

    def save_topics(self, ask_to_publish: bool = True) -> bool:
        try:
            self.topic_config = self._collect_topic_config()
            save_topic_settings(self.topic_config)
        except ValueError as exc:
            self._show_popup(APP_NAME, str(exc), kind="warning")
            return False
        self.status.set("主题设置已保存。本地发送测试会立即采用这些筛选规则。")
        if ask_to_publish and self._show_popup(
            APP_NAME,
            "主题设置已保存。\n\n是否要上传到 GitHub 云端，让之后的定时推送使用本次设置？",
            kind="question",
            choices=True,
        ):
            self._publish_saved_topics()
        return True

    def open_cloud_setup(self) -> None:
        if not self._load_github_token():
            self._start_github_login("cloud_setup")
            return
        if not self.github_profile.get("login"):
            self._open_cloud_setup_after_profile = True
            self._refresh_github_profile()
            self.status.set("正在读取 GitHub 账户信息...")
            return
        self._open_cloud_setup_dialog()

    def _open_cloud_setup_dialog(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("一键配置我的云端")
        dialog.geometry("720x760")
        dialog.minsize(660, 620)
        dialog.transient(self.root)
        self._enable_minimize_button(dialog)

        canvas = Canvas(dialog, bg="#edf3f1", highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        frame = ttk.Frame(canvas, padding=28)
        window = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        ttk.Label(frame, text="首次云端配置", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="填写完成后，软件会在你的 GitHub 账号下创建论文推送仓库、写入加密 Secrets、设置北京时间定时任务并运行一次测试。",
            style="Subtitle.TLabel",
            wraplength=630,
        ).pack(anchor="w", pady=(6, 18))

        form = ttk.Frame(frame, style="Card.TFrame", padding=22)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        values = {
            "repository": StringVar(value="robotics-paper-mailer"),
            "smtp_user": StringVar(value=self.settings.get("recipient", "")),
            "smtp_code": StringVar(),
            "recipient": StringVar(value=self.settings.get("recipient", "")),
            "hour": StringVar(value="09"),
            "minute": StringVar(value="00"),
            "zotero_api_key": StringVar(),
            "zotero_user_id": StringVar(),
            "zotero_collection": StringVar(value="机器人运控论文"),
        }
        private_repo = BooleanVar(value=True)

        def field(row: int, label: str, key: str, *, secret: bool = False) -> None:
            ttk.Label(form, text=label, style="CardText.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 18), pady=7)
            ttk.Entry(form, textvariable=values[key], show="*" if secret else "").grid(row=row, column=1, sticky="ew", pady=7)

        field(0, "GitHub 仓库名", "repository")
        ttk.Checkbutton(form, text="创建为私有仓库", variable=private_repo).grid(row=1, column=1, sticky="w", pady=(0, 8))
        field(2, "QQ 邮箱账号", "smtp_user")
        field(3, "QQ SMTP 授权码", "smtp_code", secret=True)
        field(4, "接收论文邮箱", "recipient")

        ttk.Label(form, text="每日发送时间", style="CardText.TLabel").grid(row=5, column=0, sticky="w", padx=(0, 18), pady=7)
        time_row = ttk.Frame(form, style="Card.TFrame")
        time_row.grid(row=5, column=1, sticky="w", pady=7)
        ttk.Entry(time_row, textvariable=values["hour"], width=5, justify="center").pack(side="left")
        ttk.Label(time_row, text=" : ", style="CardText.TLabel").pack(side="left")
        ttk.Entry(time_row, textvariable=values["minute"], width=5, justify="center").pack(side="left")
        ttk.Label(time_row, text=" 北京时间", style="CardText.TLabel").pack(side="left", padx=(8, 0))

        ttk.Separator(form).grid(row=6, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Label(form, text="Zotero（可选，三项都不填则跳过）", style="CardTitle.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 5))
        field(8, "Zotero API Key", "zotero_api_key", secret=True)
        field(9, "Zotero User ID", "zotero_user_id")
        field(10, "Zotero 分类名称", "zotero_collection")

        ttk.Label(
            frame,
            text="安全说明：SMTP 授权码和 Zotero API Key 只在本次操作内存中使用，经 GitHub 公钥加密后写入 Actions Secrets，不会保存到本机设置或提交到仓库。",
            style="Subtitle.TLabel",
            wraplength=630,
        ).pack(anchor="w", pady=(14, 10))

        def submit() -> None:
            repository = values["repository"].get().strip()
            smtp_user = values["smtp_user"].get().strip()
            smtp_code = values["smtp_code"].get().strip()
            recipient = values["recipient"].get().strip()
            try:
                hour = int(values["hour"].get())
                minute = int(values["minute"].get())
            except ValueError:
                self._show_popup(APP_NAME, "发送时间必须是数字。", kind="warning", parent=dialog)
                return
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repository):
                self._show_popup(APP_NAME, "仓库名只能包含字母、数字、点、横线和下划线。", kind="warning", parent=dialog)
                return
            if not smtp_user or not smtp_code or not recipient:
                self._show_popup(APP_NAME, "QQ 邮箱账号、SMTP 授权码和收件邮箱不能为空。", kind="warning", parent=dialog)
                return
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                self._show_popup(APP_NAME, "请输入有效的北京时间，例如 09:00。", kind="warning", parent=dialog)
                return
            zotero_values = [values["zotero_api_key"].get().strip(), values["zotero_user_id"].get().strip(), values["zotero_collection"].get().strip()]
            if any(zotero_values[:2]) and not all(zotero_values):
                self._show_popup(APP_NAME, "使用 Zotero 时，API Key、User ID 和分类名称需要全部填写。", kind="warning", parent=dialog)
                return
            setup = {
                "repository": repository,
                "private": private_repo.get(),
                "hour": hour,
                "minute": minute,
                "secrets": {
                    "QQ_SMTP_USER": smtp_user,
                    "QQ_SMTP_AUTH_CODE": smtp_code,
                    "MAIL_TO": recipient,
                },
            }
            if all(zotero_values):
                setup["secrets"].update({
                    "ZOTERO_API_KEY": zotero_values[0],
                    "ZOTERO_USER_ID": zotero_values[1],
                    "ZOTERO_COLLECTION_NAME": zotero_values[2],
                })
            dialog.destroy()
            self.status.set("正在创建并配置你的 GitHub 云端项目...")
            threading.Thread(target=self._cloud_setup_worker, args=(setup,), daemon=True).start()

        ttk.Button(frame, text="完成并配置云端", style="Accent.TButton", command=submit).pack(anchor="e", pady=(4, 20))

    def _workflow_content(self, hour: int, minute: int) -> bytes:
        utc_hour = (hour - 8) % 24
        return f'''name: Daily Robotics Paper Email

on:
  workflow_dispatch:
  schedule:
    - cron: "{minute} {utc_hour} * * *"

permissions:
  contents: write

jobs:
  send-paper:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Send daily paper email
        env:
          QQ_SMTP_USER: ${{{{ secrets.QQ_SMTP_USER }}}}
          QQ_SMTP_AUTH_CODE: ${{{{ secrets.QQ_SMTP_AUTH_CODE }}}}
          MAIL_TO: ${{{{ secrets.MAIL_TO }}}}
          ZOTERO_API_KEY: ${{{{ secrets.ZOTERO_API_KEY }}}}
          ZOTERO_USER_ID: ${{{{ secrets.ZOTERO_USER_ID }}}}
          ZOTERO_COLLECTION_NAME: ${{{{ secrets.ZOTERO_COLLECTION_NAME }}}}
        run: python scripts/send_daily_robotics_paper.py
      - name: Commit sent paper history
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/sent_papers.json
          git diff --cached --quiet || git commit -m "Record sent paper"
          git push
'''.encode("utf-8")

    def _github_json(self, token: str, method: str, endpoint: str, payload: object | None = None) -> object:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(endpoint, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "cloud-robotics-paper-mailer/1.0",
        })
        _, raw = self._github_request(request, timeout=45)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _github_set_secret(self, token: str, name: str, value: str) -> None:
        public_key = self._github_json(token, "GET", self.repo_api_url() + "/actions/secrets/public-key")
        key = PublicKey(base64.b64decode(public_key["key"]))
        encrypted = base64.b64encode(SealedBox(key).encrypt(value.encode("utf-8"))).decode("ascii")
        self._github_json(token, "PUT", self.repo_api_url() + "/actions/secrets/" + urllib.parse.quote(name), {
            "encrypted_value": encrypted,
            "key_id": public_key["key_id"],
        })

    def _cloud_setup_worker(self, setup: dict[str, object]) -> None:
        token = self._load_github_token()
        try:
            login = self.github_profile.get("login")
            if not login:
                user = self._github_json(token, "GET", "https://api.github.com/user")
                login = str(user["login"])
            repository = str(setup["repository"])
            try:
                repo_info = self._github_json(token, "POST", "https://api.github.com/user/repos", {
                    "name": repository,
                    "description": "机器人前沿论文自动邮件推送与 Zotero 归档",
                    "private": bool(setup["private"]),
                    "auto_init": True,
                })
            except urllib.error.HTTPError as exc:
                if exc.code != 422:
                    raise
                repo_info = self._github_json(token, "GET", f"https://api.github.com/repos/{login}/{repository}")

            self.settings.update({
                "owner": login,
                "repository": repository,
                "workflow": "daily-paper.yml",
                "schedule": f"每天 {int(setup['hour']):02d}:{int(setup['minute']):02d}（北京时间，由 GitHub Actions 触发）",
                "recipient": str(setup["secrets"]["MAIL_TO"]),
            })
            save_settings(self.settings)
            branch = str(repo_info.get("default_branch") or "main") if isinstance(repo_info, dict) else "main"
            script = resource_path("scripts/send_daily_robotics_paper.py").read_bytes()
            config = json.dumps(self.topic_config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            self._github_put_file(token, "scripts/send_daily_robotics_paper.py", script, "Install robotics paper mailer", branch=branch)
            self._github_put_file(token, "config/paper_topics.json", config, "Add personalized paper topics", branch=branch)
            self._github_put_file(token, ".github/workflows/daily-paper.yml", self._workflow_content(int(setup["hour"]), int(setup["minute"])), "Configure daily cloud schedule", branch=branch)
            for name, value in dict(setup["secrets"]).items():
                self._github_set_secret(token, str(name), str(value))
            self._trigger_cloud_worker(token, success_message=False)
            self.events.put(("cloud_setup_success", self.repo_url()))
        except Exception as exc:
            self.events.put(("error", f"云端配置未完成：{exc}"))

    def publish_topics(self) -> None:
        if not self.save_topics(ask_to_publish=False):
            return
        self._publish_saved_topics()

    def _publish_saved_topics(self) -> None:
        token = self._load_github_token()
        if token:
            self.status.set("正在发布主题设置与云端发送脚本...")
            threading.Thread(target=self._publish_topics_worker, args=(token,), daemon=True).start()
        else:
            self._start_github_login("publish")
        return
        dialog = Toplevel(self.root)
        dialog.title("发布主题设置到 GitHub")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="发布主题设置到 GitHub 云端", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="第一次使用？先创建一个 GitHub 授权 Token。它只是允许本软件更新你的个人仓库，类似临时钥匙，不是邮箱密码。", style="CardText.TLabel", wraplength=520).pack(anchor="w", pady=(8, 10))
        ttk.Button(frame, text="打开 GitHub 创建 Token 页面", style="Soft.TButton", command=lambda: webbrowser.open("https://github.com/settings/personal-access-tokens/new")).pack(anchor="w", pady=(0, 12))
        ttk.Label(frame, text="创建时只需选择 robotics-paper-mailer，并在 Repository permissions 中设置 Contents: Read and write。若还想用软件“立即触发云端任务”，再加 Actions: Read and write。", style="CardText.TLabel", wraplength=520).pack(anchor="w", pady=(0, 14))
        ttk.Label(frame, text="创建完成后复制 Token，粘贴到下面。Token 只本次使用，不会被保存。", style="CardText.TLabel", wraplength=520).pack(anchor="w", pady=(0, 8))
        token = StringVar()
        entry = ttk.Entry(frame, textvariable=token, width=64, show="*")
        entry.pack(fill="x")
        entry.focus_set()

        def submit() -> None:
            value = token.get().strip()
            if not value:
                self._show_popup(APP_NAME, "请输入 GitHub Token。", kind="warning", parent=dialog)
                return
            dialog.destroy()
            self.status.set("正在发布主题设置与云端发送脚本...")
            threading.Thread(target=self._publish_topics_worker, args=(value,), daemon=True).start()

        ttk.Button(frame, text="发布到云端", style="Accent.TButton", command=submit).pack(anchor="e", pady=(16, 0))
        dialog.bind("<Return>", lambda _event: submit())

    def _load_github_token(self) -> str:
        if not GITHUB_AUTH_PATH.exists():
            return ""
        try:
            saved = json.loads(GITHUB_AUTH_PATH.read_text(encoding="utf-8"))
            protected = str(saved.get("token_protected", "")) if isinstance(saved, dict) else ""
            return unprotect_for_current_windows_user(protected).strip() if protected else ""
        except Exception:
            return ""

    def _save_github_token(self, token: str) -> None:
        payload = {
            "token_protected": protect_for_current_windows_user(token),
            "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        GITHUB_AUTH_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def _start_github_login(self, after_login: str) -> None:
        client_id = self.settings.get("github_oauth_client_id", "").strip()
        if not client_id:
            self._open_oauth_app_setup(after_login)
            return
        self._post_auth_action = after_login
        self._oauth_cancel = threading.Event()
        dialog = Toplevel(self.root)
        self._enable_minimize_button(dialog)
        dialog.title("登录 GitHub")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        self._oauth_dialog = dialog
        self._oauth_status = StringVar(value="正在请求 GitHub 授权码...")
        self._oauth_code = StringVar(value="")
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="登录 GitHub 以授权本软件", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="浏览器将打开 GitHub 官方登录页。登录并确认授权后，本软件会自动继续，不需要创建或粘贴 Fine-grained Token。", style="CardText.TLabel", wraplength=540).pack(anchor="w", pady=(8, 12))
        ttk.Label(frame, textvariable=self._oauth_status, style="CardText.TLabel", wraplength=540).pack(anchor="w", pady=(0, 10))
        code_row = ttk.Frame(frame, style="Card.TFrame")
        code_row.pack(fill="x")
        ttk.Entry(code_row, textvariable=self._oauth_code, width=24, font=("Consolas", 16, "bold"), justify="center", state="readonly").pack(side="left")
        ttk.Button(code_row, text="复制授权码", style="Soft.TButton", command=self._copy_oauth_code).pack(side="left", padx=(10, 0))
        ttk.Label(frame, text="如果浏览器没有自动打开，请点击下面按钮。GitHub 页面会要求输入上方授权码。", style="CardText.TLabel", wraplength=540).pack(anchor="w", pady=(12, 7))
        ttk.Button(frame, text="打开 GitHub 授权页面", style="Soft.TButton", command=lambda: webbrowser.open("https://github.com/login/device")).pack(anchor="w")

        def cancel() -> None:
            self._oauth_cancel.set()
            dialog.destroy()
            self._oauth_dialog = None

        ttk.Button(frame, text="取消", style="Soft.TButton", command=cancel).pack(anchor="e", pady=(18, 0))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        threading.Thread(target=self._github_device_login_worker, args=(client_id,), daemon=True).start()

    def _open_oauth_app_setup(self, after_login: str) -> None:
        dialog = Toplevel(self.root)
        self._enable_minimize_button(dialog)
        dialog.title("首次启用 GitHub 登录")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="首次启用：创建一次 GitHub OAuth App", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="这是 GitHub 官方要求的应用身份登记，不是 Token。创建后只需把 Client ID 填到这里；以后发布和立即触发都只需点“登录 GitHub”。创建时启用 Device Flow，Homepage URL 可填本项目仓库地址，Authorization callback URL 可留空。", style="CardText.TLabel", wraplength=580).pack(anchor="w", pady=(8, 14))
        ttk.Button(frame, text="打开 GitHub OAuth App 创建页面", style="Soft.TButton", command=lambda: webbrowser.open("https://github.com/settings/developers")).pack(anchor="w", pady=(0, 14))
        ttk.Label(frame, text="GitHub OAuth App Client ID", style="CardText.TLabel").pack(anchor="w")
        client_id = StringVar(value=self.settings.get("github_oauth_client_id", ""))
        entry = ttk.Entry(frame, textvariable=client_id, width=64)
        entry.pack(fill="x", pady=(5, 0))
        entry.focus_set()

        def save_and_continue() -> None:
            value = client_id.get().strip()
            if not value:
                self._show_popup(APP_NAME, "请填写 GitHub OAuth App 的 Client ID。", kind="warning", parent=dialog)
                return
            self.settings["github_oauth_client_id"] = value
            save_settings(self.settings)
            dialog.destroy()
            self._start_github_login(after_login)

        ttk.Button(frame, text="保存并登录 GitHub", style="Accent.TButton", command=save_and_continue).pack(anchor="e", pady=(18, 0))

    def _copy_oauth_code(self) -> None:
        if self._oauth_code is None or not self._oauth_code.get():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._oauth_code.get())
        self.status.set("GitHub 授权码已复制到剪贴板。")

    def _github_device_login_worker(self, client_id: str) -> None:
        try:
            body = urllib.parse.urlencode({"client_id": client_id, "scope": "repo workflow"}).encode("utf-8")
            request = urllib.request.Request(GITHUB_DEVICE_CODE_URL, data=body, headers={"Accept": "application/json", "User-Agent": "cloud-robotics-paper-mailer/1.0"}, method="POST")
            _, raw = self._github_request(request, timeout=30)
            device = json.loads(raw.decode("utf-8"))
            device_code = str(device["device_code"])
            user_code = str(device["user_code"])
            verification_uri = str(device["verification_uri"])
            expires_at = time.monotonic() + int(device.get("expires_in", 900))
            interval = max(5, int(device.get("interval", 5)))
            self.events.put(("oauth_device", json.dumps({"user_code": user_code, "verification_uri": verification_uri})))
            webbrowser.open(verification_uri)
            while time.monotonic() < expires_at and not self._oauth_cancel.wait(interval):
                payload = urllib.parse.urlencode({"client_id": client_id, "device_code": device_code, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).encode("utf-8")
                poll = urllib.request.Request(GITHUB_ACCESS_TOKEN_URL, data=payload, headers={"Accept": "application/json", "User-Agent": "cloud-robotics-paper-mailer/1.0"}, method="POST")
                _, token_raw = self._github_request(poll, timeout=30)
                result = json.loads(token_raw.decode("utf-8"))
                token = str(result.get("access_token", "")).strip()
                if token:
                    self.events.put(("oauth_success", token))
                    return
                error = str(result.get("error", "authorization_pending"))
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                raise RuntimeError(result.get("error_description", error))
            if not self._oauth_cancel.is_set():
                raise RuntimeError("GitHub 授权已超时，请重新登录。")
        except Exception as exc:
            if not self._oauth_cancel.is_set():
                self.events.put(("error", f"GitHub 登录失败：{exc}"))

    def open_github_account(self) -> None:
        if not self._load_github_token():
            self._start_github_login("profile")
            return
        if self.github_profile.get("login"):
            self._open_github_account_dialog()
            return
        self._refresh_github_profile(open_dialog=True)

    def _refresh_github_profile(self, open_dialog: bool = False) -> None:
        token = self._load_github_token()
        self._open_profile_after_refresh = self._open_profile_after_refresh or open_dialog
        if not token:
            self.github_profile = {}
            self.github_account_text.set("登录 GitHub")
            if self.github_account_button is not None:
                self.github_account_button.configure(image="")
            return
        threading.Thread(target=self._github_profile_worker, args=(token,), daemon=True).start()

    def _github_profile_worker(self, token: str) -> None:
        try:
            request = urllib.request.Request(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "cloud-robotics-paper-mailer/1.0",
                },
            )
            _, raw = self._github_request(request, timeout=30)
            user = json.loads(raw.decode("utf-8"))
            profile = {
                "login": str(user.get("login", "")),
                "name": str(user.get("name") or user.get("login", "")),
                "html_url": str(user.get("html_url", "")),
                "avatar_url": str(user.get("avatar_url", "")),
            }
            avatar_url = profile["avatar_url"]
            if avatar_url:
                try:
                    avatar_request = urllib.request.Request(avatar_url, headers={"User-Agent": "cloud-robotics-paper-mailer/1.0"})
                    with urllib.request.urlopen(avatar_request, timeout=20) as response:
                        profile["avatar_data"] = base64.b64encode(response.read()).decode("ascii")
                except Exception:
                    pass
            self.events.put(("github_profile", json.dumps(profile)))
        except Exception:
            self.events.put(("github_profile", "{}"))

    def _apply_github_profile(self, profile: dict[str, str]) -> None:
        self.github_profile = profile
        login = profile.get("login", "")
        if not login:
            self.github_account_text.set("登录 GitHub")
            if self.github_account_button is not None:
                self.github_account_button.configure(image="")
            return
        self.github_account_text.set("@" + login)
        avatar_data = profile.get("avatar_data", "")
        if avatar_data:
            try:
                image = tk.PhotoImage(data=avatar_data)
                divisor = max(1, max(image.width(), image.height()) // 32)
                self.github_avatar_image = image.subsample(divisor, divisor)
            except tk.TclError:
                self.github_avatar_image = None
        if self.github_account_button is not None:
            self.github_account_button.configure(image=self.github_avatar_image or "")

    def _open_github_account_dialog(self) -> None:
        if not self.github_profile.get("login"):
            return
        dialog = Toplevel(self.root)
        self._enable_minimize_button(dialog)
        dialog.title("GitHub 账户")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        if self.github_avatar_image is not None:
            tk.Label(frame, image=self.github_avatar_image, bg="#ffffff").pack(anchor="w")
        ttk.Label(frame, text=self.github_profile.get("name", "GitHub 用户"), style="CardTitle.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(frame, text="@" + self.github_profile.get("login", ""), style="CardText.TLabel").pack(anchor="w", pady=(3, 12))
        ttk.Label(frame, text="已通过 GitHub 官方授权登录。本软件只保存本机加密令牌，不保存 GitHub 密码。", style="CardText.TLabel", wraplength=440).pack(anchor="w")
        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="打开 GitHub 主页", style="Soft.TButton", command=lambda: webbrowser.open(self.github_profile.get("html_url", "https://github.com"))).pack(side="left")
        ttk.Button(buttons, text="切换账号", style="Soft.TButton", command=lambda: self._sign_out_github(dialog, sign_in_again=True)).pack(side="left", padx=(9, 0))
        ttk.Button(buttons, text="退出登录", style="Soft.TButton", command=lambda: self._sign_out_github(dialog, sign_in_again=False)).pack(side="right")

    def _sign_out_github(self, dialog: Toplevel, sign_in_again: bool) -> None:
        self._oauth_cancel.set()
        try:
            GITHUB_AUTH_PATH.unlink(missing_ok=True)
        except OSError as exc:
            self._show_popup(APP_NAME, f"无法删除本机 GitHub 登录状态：{exc}", kind="error", parent=dialog)
            return
        dialog.destroy()
        self.github_profile = {}
        self.github_avatar_image = None
        self.github_account_text.set("登录 GitHub")
        if self.github_account_button is not None:
            self.github_account_button.configure(image="")
        self.status.set("已退出 GitHub 登录。")
        if sign_in_again:
            self._start_github_login("profile")

    def _github_put_file(self, token: str, path: str, content: bytes, message: str, *, branch: str | None = None) -> None:
        api_base = self.repo_api_url()
        if branch is None:
            repository = self._github_json(token, "GET", api_base)
            branch = str(repository.get("default_branch") or "main") if isinstance(repository, dict) else "main"
        endpoint = api_base + "/contents/" + urllib.parse.quote(path)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cloud-robotics-paper-mailer/1.0",
        }
        sha = None
        try:
            request = urllib.request.Request(endpoint + "?ref=" + urllib.parse.quote(branch), headers=headers, method="GET")
            _, raw = self._github_request(request, timeout=30)
            existing = json.loads(raw.decode("utf-8"))
            sha = existing.get("sha")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        payload: dict[str, str] = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT")
        self._github_request(request, timeout=45)

    def _github_request(self, request: urllib.request.Request, timeout: int) -> tuple[int, bytes]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError:
                raise
            except (http.client.RemoteDisconnected, TimeoutError, OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"GitHub request failed after retries: {last_error}")

    def _github_verify_repository(self, token: str) -> None:
        endpoint = self.repo_api_url()
        request = urllib.request.Request(endpoint, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cloud-robotics-paper-mailer/1.0",
        })
        self._github_request(request, timeout=30)

    def _publish_topics_worker(self, token: str) -> None:
        try:
            self._github_verify_repository(token)
            script = resource_path("scripts/send_daily_robotics_paper.py").read_bytes()
            config = json.dumps(self.topic_config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            self._github_put_file(token, "scripts/send_daily_robotics_paper.py", script, "Enable personalized paper topics")
            self._github_put_file(token, "config/paper_topics.json", config, "Update personalized paper topics")
            self.events.put(("info", "主题设置已发布到 GitHub。下一次云端定时发送会使用新规则。"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 404:
                message = (
                    f"GitHub 找不到或拒绝 Token 访问仓库 {self.settings['owner']}/{self.settings['repository']}（HTTP 404）。\n\n"
                    "请回到 GitHub Token 页面，确认：\n"
                    "1. Repository access 选择 Only select repositories；\n"
                    "2. 已实际勾选 robotics-paper-mailer；\n"
                    "3. Repository permissions 中 Contents 是 Read and write。\n\n"
                    "GitHub 对没有仓库访问权的私有仓库也会返回 404。"
                )
            else:
                message = f"发布失败（HTTP {exc.code}）。请确认 Token 具有 Contents: Read and write 权限。\n{detail}"
            self.events.put(("error", message))
        except Exception as exc:
            self.events.put(("error", f"发布主题设置失败：{exc}"))

    def refresh_status(self) -> None:
        smtp_ready = all(os.environ.get(key, "").strip() for key in ("QQ_SMTP_USER", "QQ_SMTP_AUTH_CODE"))
        zotero_ready = all(os.environ.get(key, "").strip() for key in ("ZOTERO_API_KEY", "ZOTERO_USER_ID", "ZOTERO_COLLECTION_NAME"))
        smtp_text = "QQ SMTP 已就绪" if smtp_ready else "未检测到本地 QQ SMTP 环境变量"
        zotero_text = "Zotero 已就绪" if zotero_ready else "未检测到本地 Zotero 环境变量（可只测试邮件）"
        self.local_env_status.set(f"{smtp_text}\n{zotero_text}")
        self.status.set("环境检查完成。云端定时任务不依赖此电脑。")

    def save_public_settings(self) -> None:
        updated = {key: value.get().strip() for key, value in self.fields.items()}
        updated["github_oauth_client_id"] = self.settings.get("github_oauth_client_id", "")
        self.settings = updated
        save_settings(self.settings)
        self.status.set("公开配置已保存。重新打开软件后仍会保留。")
        self._show_popup(APP_NAME, "已保存。GitHub、QQ SMTP 和 Zotero 的密钥仍仅保留在云端 Secrets 或本地环境变量中。")

    def repo_url(self) -> str:
        return f"https://github.com/{self.settings['owner']}/{self.settings['repository']}"

    def repo_api_url(self) -> str:
        return f"https://api.github.com/repos/{self.settings['owner']}/{self.settings['repository']}"

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        match = re.search(r"\d+(?:\.\d+)*", value)
        return tuple(int(part) for part in match.group(0).split(".")) if match else (0,)

    def check_for_updates(self, manual: bool = False) -> None:
        self._update_check_manual = self._update_check_manual or manual
        if self._update_check_running:
            if manual:
                self.status.set("软件更新正在检查中，请稍候...")
            return
        self._update_check_running = True
        if manual:
            self.status.set("正在检查软件更新...")
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _check_for_updates_worker(self) -> None:
        try:
            headers = {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"cloud-robotics-paper-mailer/{APP_VERSION}",
            }
            token = self._load_github_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            request = urllib.request.Request(
                UPDATE_API_URL,
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                release = json.loads(response.read().decode("utf-8"))
            latest = str(release.get("tag_name", ""))
            if self._version_tuple(latest) <= self._version_tuple(APP_VERSION):
                self.events.put(("update_none", latest or APP_VERSION))
                return
            assets = release.get("assets", [])
            asset = next((item for item in assets if item.get("name") == UPDATE_ASSET_NAME), None)
            if asset is None:
                asset = next((item for item in assets if str(item.get("name", "")).lower().endswith(".exe")), None)
            if asset is None:
                raise RuntimeError("最新 Release 中没有找到 Windows EXE 安装文件。")
            update = {
                "version": latest,
                "name": str(release.get("name") or latest),
                "notes": str(release.get("body") or "本次版本未提供更新说明。"),
                "html_url": str(release.get("html_url", "")),
                "download_url": str(asset["browser_download_url"]),
                "digest": str(asset.get("digest") or ""),
                "size": int(asset.get("size") or 0),
            }
            self.events.put(("update_available", json.dumps(update, ensure_ascii=False)))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.events.put(("update_unpublished", ""))
            elif exc.code == 403:
                self.events.put(("update_error", "GitHub 暂时限制了更新检查请求。请稍后重试；登录 GitHub 后可提高检查限额。"))
            else:
                self.events.put(("update_error", f"检查更新失败（HTTP {exc.code}）。"))
        except Exception as exc:
            self.events.put(("update_error", f"检查更新失败：{exc}"))

    def _show_update_dialog(self, update: dict[str, object]) -> None:
        self._pending_update = update
        dialog = Toplevel(self.root)
        dialog.title("发现软件更新")
        dialog.geometry("620x470")
        dialog.minsize(560, 420)
        dialog.transient(self.root)
        self._enable_minimize_button(dialog)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"发现新版本 {update['version']}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text=f"当前版本 v{APP_VERSION}。更新不会删除主题配置、GitHub 登录状态或本地历史。", style="Subtitle.TLabel", wraplength=550).pack(anchor="w", pady=(6, 14))
        notes = Text(frame, height=12, font=("Microsoft YaHei UI", 10), bg="#ffffff", fg="#173a36", relief="flat", padx=12, pady=10, wrap="word")
        notes.pack(fill="both", expand=True)
        notes.insert("1.0", str(update["notes"]))
        notes.configure(state="disabled")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(14, 0))
        if update.get("html_url"):
            ttk.Button(buttons, text="查看发布页面", style="Soft.TButton", command=lambda: webbrowser.open(str(update["html_url"]))).pack(side="left")

        def install() -> None:
            dialog.destroy()
            self.status.set(f"正在下载 {update['version']}，请不要关闭软件...")
            threading.Thread(target=self._download_update_worker, args=(update,), daemon=True).start()

        ttk.Button(buttons, text="稍后更新", style="Soft.TButton", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="下载并更新", style="Accent.TButton", command=install).pack(side="right", padx=(0, 9))

    def _download_update_worker(self, update: dict[str, object]) -> None:
        try:
            if not getattr(sys, "frozen", False):
                raise RuntimeError("开发模式不能自动覆盖 Python；请在打包后的 EXE 中测试更新。")
            download_path = Path(tempfile.gettempdir()) / f"robotics-paper-mailer-{update['version']}.exe"
            request = urllib.request.Request(str(update["download_url"]), headers={"User-Agent": f"cloud-robotics-paper-mailer/{APP_VERSION}"})
            hasher = hashlib.sha256()
            total = 0
            with urllib.request.urlopen(request, timeout=120) as response, download_path.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    hasher.update(chunk)
                    total += len(chunk)
            expected_size = int(update.get("size") or 0)
            if expected_size and total != expected_size:
                raise RuntimeError(f"下载文件大小异常：应为 {expected_size} 字节，实际为 {total} 字节。")
            digest = str(update.get("digest") or "")
            if digest:
                algorithm, _, expected_hash = digest.partition(":")
                if algorithm.lower() != "sha256" or hasher.hexdigest().lower() != expected_hash.lower():
                    raise RuntimeError("更新文件 SHA-256 校验失败，已停止安装。")
            self.events.put(("update_downloaded", str(download_path)))
        except Exception as exc:
            try:
                download_path.unlink(missing_ok=True)
            except (OSError, UnboundLocalError):
                pass
            self.events.put(("error", f"软件下载或校验失败：{exc}"))

    def _install_downloaded_update(self, download_path: str) -> None:
        target = Path(sys.executable).resolve()
        source = Path(download_path).resolve()
        updater_path = Path(tempfile.gettempdir()) / "robotics-paper-mailer-update.ps1"
        backup = target.with_suffix(target.suffix + ".backup")
        quote = lambda value: str(value).replace("'", "''")
        updater = "\n".join([
            f"$targetPid = {os.getpid()}",
            f"$bootloaderPid = {os.getppid()}",
            "Wait-Process -Id $targetPid -ErrorAction SilentlyContinue",
            "if ($bootloaderPid -ne $targetPid) { Wait-Process -Id $bootloaderPid -ErrorAction SilentlyContinue }",
            "Start-Sleep -Seconds 2",
            "$ErrorActionPreference = 'Stop'",
            "try {",
            f"  Copy-Item -LiteralPath '{quote(target)}' -Destination '{quote(backup)}' -Force",
            "  $copied = $false",
            "  for ($attempt = 1; $attempt -le 5; $attempt++) {",
            "    try {",
            f"      Copy-Item -LiteralPath '{quote(source)}' -Destination '{quote(target)}' -Force",
            "      $copied = $true",
            "      break",
            "    } catch {",
            "      if ($attempt -eq 5) { throw }",
            "      Start-Sleep -Seconds 2",
            "    }",
            "  }",
            "  if (-not $copied) { throw 'Unable to replace application executable.' }",
            "  Start-Sleep -Seconds 2",
            f"  Start-Process -FilePath '{quote(target)}'",
            f"  Remove-Item -LiteralPath '{quote(source)}' -Force -ErrorAction SilentlyContinue",
            "} catch {",
            f"  if (Test-Path -LiteralPath '{quote(backup)}') {{ Copy-Item -LiteralPath '{quote(backup)}' -Destination '{quote(target)}' -Force }}",
            "  Add-Type -AssemblyName PresentationFramework",
            "  [System.Windows.MessageBox]::Show('自动更新失败，已恢复旧版本。请稍后重试。', '机器人论文云端助手') | Out-Null",
            "}",
            "Remove-Item -LiteralPath $PSCommandPath -Force",
        ]) + "\n"
        updater_path.write_text(updater, encoding="utf-8-sig")
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater_path)],
            creationflags=0x08000000,
            close_fds=True,
        )
        self.root.destroy()

    def open_actions(self) -> None:
        webbrowser.open(self.repo_url() + "/actions")

    def trigger_cloud(self) -> None:
        token = self._load_github_token()
        if token:
            self.status.set("正在请求 GitHub 启动云端任务...")
            threading.Thread(target=self._trigger_cloud_worker, args=(token,), daemon=True).start()
        else:
            self._start_github_login("trigger")
        return
        dialog = Toplevel(self.root)
        dialog.title("立即触发云端任务")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="临时输入 GitHub Fine-grained Token", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Token 仅用于本次 HTTPS 请求，不会写入磁盘。它需要对该仓库有 Actions: Read and write 权限。", style="CardText.TLabel", wraplength=460).pack(anchor="w", pady=(8, 14))
        token = StringVar()
        entry = ttk.Entry(frame, textvariable=token, width=62, show="*")
        entry.pack(fill="x")
        entry.focus_set()

        def submit() -> None:
            value = token.get().strip()
            if not value:
                self._show_popup(APP_NAME, "请输入 GitHub Token。", kind="warning", parent=dialog)
                return
            dialog.destroy()
            self.status.set("正在请求 GitHub 启动云端任务...")
            threading.Thread(target=self._trigger_cloud_worker, args=(value,), daemon=True).start()

        ttk.Button(frame, text="触发云端发送", style="Accent.TButton", command=submit).pack(anchor="e", pady=(16, 0))
        dialog.bind("<Return>", lambda _event: submit())

    def _trigger_cloud_worker(self, token: str, success_message: bool = True) -> None:
        endpoint = self.repo_api_url() + f"/actions/workflows/{self.settings['workflow']}/dispatches"
        data = json.dumps({"ref": "main"}).encode("utf-8")
        request = urllib.request.Request(endpoint, data=data, method="POST", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            if success_message:
                self.events.put(("info", "GitHub 已接受请求，云端任务通常会在几十秒内开始。请在 GitHub Actions 查看执行日志。"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.events.put(("error", f"云端任务没有触发（HTTP {exc.code}）。\n{detail}"))
        except Exception as exc:
            self.events.put(("error", f"触发云端任务失败：{exc}"))

    def run_local_test(self) -> None:
        if not os.environ.get("QQ_SMTP_USER", "").strip() or not os.environ.get("QQ_SMTP_AUTH_CODE", "").strip():
            self._show_popup(APP_NAME, "本地环境没有 QQ SMTP 变量。请使用“立即触发一次云端任务”，或先在 Windows 设置 QQ_SMTP_USER 和 QQ_SMTP_AUTH_CODE。", kind="warning")
            return
        if not self._show_popup(APP_NAME, "这会立即检索论文，并向邮箱发送一封测试邮件。是否继续？", kind="question", choices=True):
            return
        self.status.set("正在本地检索论文并发送邮件。这个过程可能需要数分钟...")
        threading.Thread(target=self._local_test_worker, daemon=True).start()

    def _local_test_worker(self) -> None:
        try:
            os.environ["PAPER_CONFIG_PATH"] = str(TOPIC_CONFIG_PATH)
            module = load_sender_module()
            module.HISTORY_PATH = LOCAL_HISTORY_PATH
            result = module.main()
            if result != 0:
                raise RuntimeError(f"发送脚本退出码为 {result}")
            self.events.put(("info", "本地测试邮件已发送。请检查 QQ 邮箱和 Zotero 文件夹。"))
        except Exception as exc:
            self.events.put(("error", f"本地测试失败：{exc}"))

    def refresh_history(self) -> None:
        self.history_text.configure(state="normal")
        self.history_text.delete("1.0", "end")
        if not LOCAL_HISTORY_PATH.exists():
            self.history_text.insert("end", "尚未通过本软件完成本地发送测试。\n\n云端历史请在 GitHub 仓库的 data/sent_papers.json 中查看。")
        else:
            try:
                records = json.loads(LOCAL_HISTORY_PATH.read_text(encoding="utf-8"))
                for record in records:
                    self.history_text.insert("end", f"{record.get('sent_at', '')}\n{record.get('title', '')}\n{record.get('url', '')}\n\n")
            except (OSError, json.JSONDecodeError) as exc:
                self.history_text.insert("end", f"无法读取历史记录：{exc}")
        self.history_text.configure(state="disabled")

    def poll_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "oauth_device":
                    try:
                        device = json.loads(message)
                        if self._oauth_code is not None:
                            self._oauth_code.set(str(device["user_code"]))
                        if self._oauth_status is not None:
                            self._oauth_status.set("请到浏览器登录 GitHub，并输入上方授权码。正在等待授权...")
                    except (KeyError, TypeError, json.JSONDecodeError):
                        self.events.put(("error", "GitHub 返回的授权信息格式异常。"))
                    continue
                if kind == "github_profile":
                    try:
                        profile = json.loads(message)
                        self._apply_github_profile(profile if isinstance(profile, dict) else {})
                        if self._open_profile_after_refresh and self.github_profile.get("login"):
                            self._open_profile_after_refresh = False
                            self._open_github_account_dialog()
                        if self._open_cloud_setup_after_profile and self.github_profile.get("login"):
                            self._open_cloud_setup_after_profile = False
                            self._open_cloud_setup_dialog()
                    except (TypeError, json.JSONDecodeError):
                        self._apply_github_profile({})
                    continue
                if kind == "oauth_success":
                    try:
                        self._save_github_token(message)
                        if self._oauth_dialog is not None and self._oauth_dialog.winfo_exists():
                            self._oauth_dialog.destroy()
                        self._oauth_dialog = None
                        action = self._post_auth_action
                        self._post_auth_action = None
                        if action == "publish":
                            self.status.set("GitHub 已登录，正在发布主题设置与云端发送脚本...")
                            threading.Thread(target=self._publish_topics_worker, args=(message,), daemon=True).start()
                        elif action == "trigger":
                            self.status.set("GitHub 已登录，正在请求启动云端任务...")
                            threading.Thread(target=self._trigger_cloud_worker, args=(message,), daemon=True).start()
                        elif action == "profile":
                            self.status.set("GitHub 登录完成，正在读取账户信息...")
                            self._refresh_github_profile(open_dialog=True)
                        elif action == "cloud_setup":
                            self.status.set("GitHub 登录完成，正在读取账户信息...")
                            self._open_cloud_setup_after_profile = True
                            self._refresh_github_profile()
                        else:
                            self._show_popup(APP_NAME, "GitHub 登录完成。")
                    except Exception as exc:
                        self.events.put(("error", f"无法保存 GitHub 登录状态：{exc}"))
                    continue
                if kind == "cloud_setup_success":
                    self.status.set("云端项目配置完成，已启动首次测试。")
                    self._show_popup(
                        APP_NAME,
                        "云端配置完成。\n\n已创建或更新你的 GitHub 仓库、加密写入 Secrets、设置每日定时任务，并启动首次发送测试。\n\n仓库地址：" + message,
                    )
                    continue
                if kind == "update_available":
                    self._update_check_running = False
                    self._update_check_manual = False
                    try:
                        update = json.loads(message)
                        self._show_update_dialog(update)
                    except (TypeError, json.JSONDecodeError):
                        self._show_popup(APP_NAME, "GitHub 返回的更新信息格式异常。", kind="error")
                    continue
                if kind == "update_none":
                    self._update_check_running = False
                    was_manual = self._update_check_manual
                    self._update_check_manual = False
                    self.status.set(f"当前已是最新版 v{APP_VERSION}。")
                    if was_manual:
                        self._show_popup(APP_NAME, f"当前已是最新版 v{APP_VERSION}。")
                    continue
                if kind == "update_unpublished":
                    self._update_check_running = False
                    was_manual = self._update_check_manual
                    self._update_check_manual = False
                    if was_manual:
                        self._show_popup(APP_NAME, "官方仓库尚未发布第一个 GitHub Release，因此暂时没有可下载更新。", kind="warning")
                    continue
                if kind == "update_error":
                    self._update_check_running = False
                    was_manual = self._update_check_manual
                    self._update_check_manual = False
                    if was_manual:
                        self._show_popup(APP_NAME, message, kind="warning")
                    continue
                if kind == "update_downloaded":
                    self.status.set("更新下载并校验完成，正在重新启动软件...")
                    self._install_downloaded_update(message)
                    continue
                self.status.set(message.replace("\n", " "))
                if kind == "info":
                    self.refresh_history()
                    self._show_popup(APP_NAME, message)
                else:
                    self._show_popup(APP_NAME, message, kind="error")
        except queue.Empty:
            pass
        self.root.after(200, self.poll_events)


def main() -> None:
    if "--verify-bundled-script" in sys.argv:
        load_sender_module()
        return
    root = Tk()
    PaperMailerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
