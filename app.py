"""Desktop window for Slurm jobs on any number of Linux accounts."""

from __future__ import annotations

import ctypes
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import winsound
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk

from ask import AskError, ask_deepseek, completions_url, snapshot_text
from plans import PlanBoard, PlanRemind, center_on, due_plans, tell
from shellwin import ShellWindow
from jobs import (
    AccountResult,
    Job,
    elapsed_seconds,
    finished_since,
    forget_host_key,
    job_bucket,
    job_key,
    kind,
    next_buckets,
    one_line,
    query_account,
    query_top,
    queue_text,
    short_time,
    state_text,
)
from store import Store, _check_login, check_user, data_dir, last_user_name, legacy_waiting, register_user, user_folder
from theme import SKINS, TEXT_CHOICES, TEXT_SIZES, apply_text, palette, restyle, sync_modules, text_look
from updater import UpdateError, download_release, launch_swap, look_for_update, save_update_url, update_url
import i18n
from winsecret import SecretError

REFRESH_SECONDS = 10 * 60
UPDATE_CHECK_HOURS = 24
BG = "#10141c"
PANEL = "#1a2130"
CARD = "#222b3c"
FG = "#f3f6fb"
MUTED = "#8b98ad"
ACCENT = "#6c8cff"
OK = "#3dce8f"
WARN = "#f2b544"
BAD = "#ff6d7d"
LINE = "#313c52"
HEADING = "#2a384c"
VERSION = "1.0.15"
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 18, "bold")
COLUMNS = [
    ("account", "账号", 140, False),
    ("job_id", "作业号", 110, False),
    ("name", "作业名", 180, True),
    ("state", "状态", 90, False),
    ("elapsed", "已运行", 90, False),
    ("limit", "时限", 90, False),
    ("partition", "分区", 80, False),
    ("cpus", "核数", 50, False),
    ("memory", "内存", 70, False),
    ("place", "节点/原因", 200, True),
    ("submit", "提交时间", 110, False),
]
FILTERS = (
    ("all", "全部"),
    ("run", "运行中"),
    ("wait", "排队"),
    ("done", "已完成"),
    ("bad", "报错"),
)
BRIEF = (
    ("run", "运行中"),
    ("wait", "排队"),
    ("done", "已完成"),
    ("bad", "报错"),
)


def _bucket_ink(key: str) -> str:
    if key == "wait":
        return WARN
    if key == "bad":
        return BAD
    return OK
BALL = "#0078D4"
NO_ACCOUNT = "还没有账号。先填写下面的主机、端口、用户名和密码。"


def _icon_file():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    path = base / "quill.ico"
    return path if path.exists() else None


def _enable_dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _crash(exc: BaseException) -> None:
    import traceback

    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    where = "crash.log"
    try:
        path = data_dir() / "crash.log"
        path.write_text(text, encoding="utf-8")
        where = str(path)
    except Exception:
        pass
    ctypes.windll.user32.MessageBoxW(None, f"作业看台出错了：{exc}\n\n详情：{where}", "作业看台", 0x10)


def _job_sort_id(job_id: str) -> tuple:
    match = re.match(r"(\d+)", job_id or "")
    number = int(match.group(1)) if match else -1
    return (number, job_id or "")


def _cpu_sort(value: str) -> int:
    try:
        return int(str(value).split()[0])
    except (TypeError, ValueError):
        return -1


def _column_value(column: str, job: Job):
    if column == "account":
        return job.account_label.casefold()
    if column == "job_id":
        return _job_sort_id(job.job_id)
    if column == "name":
        return job.name.casefold()
    if column == "state":
        return state_text(job.state)
    if column == "elapsed":
        return elapsed_seconds(job.elapsed)
    if column == "limit":
        return elapsed_seconds(job.timelimit)
    if column == "partition":
        return job.partition.casefold()
    if column == "cpus":
        return _cpu_sort(job.cpus)
    if column == "memory":
        return job.memory.casefold()
    if column == "place":
        return job.place.casefold()
    if column == "submit":
        return job.submit or ""
    return ""


def _setup_gap(error: str) -> bool:
    return "还没有填写密码" in error or "主机或用户名是空的" in error


class FloatBall(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.app = app
        self.size = 108
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#010101")
        try:
            self.wm_attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self, width=self.size, height=self.size, bg="#010101", highlightthickness=0, cursor="hand2")
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Enter>", self._enter)
        self.canvas.bind("<Leave>", self._leave)
        self.tip = None
        self.tip_label = None
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="打开", command=app.restore_from_ball)
        self.menu.add_command(label="立即刷新", command=self._refresh)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self._quit)
        self._moved = False
        self.withdraw()

    def render(self, run: int, wait: int, done: int) -> None:
        canvas = self.canvas
        canvas.delete("all")
        span = self.size
        canvas.create_oval(6, 6, span - 6, span - 6, fill=palette.accent, outline=palette.on_accent, width=2)
        active = run + wait
        size = 24 if active < 100 else 19
        canvas.create_text(span / 2, 48, text=f"{run}/{active}", fill=palette.on_accent, font=("Microsoft YaHei UI", size, "bold"))
        canvas.create_text(span / 2, 80, text=f"✓ {done}", fill=palette.on_accent, font=("Segoe UI Symbol", 10))

    def show(self, run: int, wait: int, done: int) -> None:
        self.render(run, wait, done)
        pos = self.app.store.data.get("ball_pos") or []
        if isinstance(pos, list) and len(pos) == 2:
            try:
                x, y = int(pos[0]), int(pos[1])
            except (TypeError, ValueError):
                x, y = self._default_pos()
        else:
            x, y = self._default_pos()
        x = max(0, min(x, self.winfo_screenwidth() - self.size))
        y = max(0, min(y, self.winfo_screenheight() - self.size))
        self.geometry(f"{self.size}x{self.size}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)

    def hide(self) -> None:
        self._hide_tip()
        self.withdraw()

    def _enter(self, _event) -> None:
        if not self._moved:
            self._show_tip()

    def _leave(self, _event) -> None:
        self._hide_tip()

    def _show_tip(self) -> None:
        if self.tip is None:
            self.tip = tk.Toplevel(self)
            self.tip.overrideredirect(True)
            self.tip.attributes("-topmost", True)
            self.tip.configure(bg=palette.accent)
            self.tip_label = tk.Label(self.tip, text="", bg=palette.accent, fg=palette.on_accent, justify="left", font=FONT, padx=12, pady=8)
            self.tip_label.pack()
        self.tip_label.configure(text=self.app.ball_detail())
        self.tip.update_idletasks()
        width = self.tip.winfo_width()
        x = self.winfo_x() - width - 12
        if x < 8:
            x = self.winfo_x() + self.size + 12
        y = max(8, self.winfo_y())
        self.tip.geometry(f"+{x}+{y}")
        self.tip.deiconify()

    def _hide_tip(self) -> None:
        if self.tip is not None:
            self.tip.withdraw()

    def _default_pos(self) -> tuple[int, int]:
        return self.winfo_screenwidth() - self.size - 28, self.winfo_screenheight() - self.size - 72

    def _down(self, event) -> None:
        self._ox = event.x_root
        self._oy = event.y_root
        self._wx = self.winfo_x()
        self._wy = self.winfo_y()
        self._moved = False

    def _drag(self, event) -> None:
        dx = event.x_root - self._ox
        dy = event.y_root - self._oy
        if abs(dx) > 4 or abs(dy) > 4:
            self._moved = True
            self._hide_tip()
        self.geometry(f"+{self._wx + dx}+{self._wy + dy}")

    def _up(self, _event) -> None:
        if self._moved:
            self.app.store.data["ball_pos"] = [self.winfo_x(), self.winfo_y()]
            self.app.store.save()
            return
        self.app.restore_from_ball()

    def _menu(self, event) -> None:
        self.menu.tk_popup(event.x_root, event.y_root)

    def _refresh(self) -> None:
        self.app.restore_from_ball()
        self.app.refresh()

    def _quit(self) -> None:
        if messagebox.askyesno("退出", "要退出作业看台吗？", parent=self):
            self.app.on_close()


class DonePopup(tk.Toplevel):
    def __init__(self, app: "App", jobs: list[Job]) -> None:
        super().__init__(app.popup_parent())
        self.withdraw()
        self.app = app
        self.remaining = list(jobs)
        self.title("作业跑完了")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.defer_rest)
        self.bind("<Escape>", lambda _event: self.defer_rest())
        self._popup_width = 460
        self._popup_height = min(560, 190 + 96 * len(jobs))
        tk.Frame(self, bg=OK, height=4).pack(fill="x")
        tk.Label(self, text=f"{len(jobs)} 个作业跑完了", bg=BG, fg=FG, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(self, text="可以现在打开，或先放着稍后处理。", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(0, 8))
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=min(380, 88 * len(jobs)))
        inner = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.pack(side="left", fill="both", expand=True)
        if len(jobs) > 3:
            scroll = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))
        for job in jobs:
            self._row(inner, job)
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(bar, text="全部稍后处理", style="Ghost.TButton", command=self.defer_rest).pack(side="right")
        owner = app if app.winfo_viewable() else self.master
        center_on(self, owner, self._popup_width, self._popup_height)
        self.deiconify()
        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _row(self, parent, job: Job) -> None:
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=10, pady=8)
        card.pack(fill="x", pady=4)
        tk.Label(card, text=f"{self.app.display_account(job)}    {job.name or job.job_id}", bg=CARD, fg=FG, font=FONT, anchor="w").pack(fill="x")
        tk.Label(card, text=f"{state_text(job.state)}    作业号 {job.job_id}    用时 {job.elapsed or '—'}", bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(2, 6))
        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x")
        ttk.Button(actions, text="现在查看", style="Accent.TButton", command=lambda item=job, box=card: self.view_now(item, box)).pack(side="left")
        ttk.Button(actions, text="稍后处理", style="Ghost.TButton", command=lambda item=job, box=card: self.defer_one(item, box)).pack(side="left", padx=(8, 0))

    def view_now(self, job: Job, card: tk.Frame | None = None) -> None:
        if card is not None:
            card.destroy()
        self.remaining = [item for item in self.remaining if job_key(item) != job_key(job)]
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        self.app.show_job(job)
        if not self.remaining:
            self.destroy()

    def defer_one(self, job: Job, card: tk.Frame | None = None) -> None:
        if card is not None:
            card.destroy()
        self.remaining = [item for item in self.remaining if job_key(item) != job_key(job)]
        self.app.defer(job)
        if not self.remaining:
            self.destroy()

    def defer_rest(self) -> None:
        for job in self.remaining:
            self.app.defer(job)
        self.remaining = []
        self.destroy()


class LaterWindow(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title("稍后处理")
        self.configure(bg=BG)
        self.minsize(420, 280)
        tk.Label(self, text="这些完成提醒先留着", bg=BG, fg=FG, font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 6))
        self.box = tk.Listbox(self, bg=CARD, fg=FG, selectbackground=ACCENT, selectforeground=palette.on_accent, relief="flat", highlightthickness=1, highlightbackground=LINE, activestyle="none", exportselection=False, font=FONT)
        self.box.pack(fill="both", expand=True, padx=16, pady=6)
        self.jobs: list[Job] = []
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(bar, text="现在查看", style="Accent.TButton", command=self.view_selected).pack(side="left")
        ttk.Button(bar, text="移除", style="Ghost.TButton", command=self.drop_selected).pack(side="left", padx=8)
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        self.reload()
        self.box.bind("<Double-1>", lambda _event: self.view_selected())
        center_on(self, app, 520, 360)
        self.deiconify()

    def reload(self) -> None:
        found, _missing = self.app.later_jobs()
        self.jobs = found
        self.box.delete(0, "end")
        for job in found:
            self.box.insert("end", f"{self.app.display_account(job)}    {job.name or job.job_id}    {job.job_id}")
        if not found:
            self.box.insert("end", "没有还在列表里的稍后任务。")

    def _selected(self) -> Job | None:
        picked = self.box.curselection()
        if not picked or picked[0] >= len(self.jobs):
            return None
        return self.jobs[picked[0]]

    def view_selected(self) -> None:
        job = self._selected()
        if job is None:
            return
        self.app.show_job(job)
        self.reload()

    def drop_selected(self) -> None:
        job = self._selected()
        if job is None:
            return
        self.app.drop_later(job)
        self.reload()


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title("DeepSeek")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        self.base_var = tk.StringVar(value=app.store.api_base())
        self.model_var = tk.StringVar(value=app.store.api_model())
        self.key_var = tk.StringVar()
        self.show_var = tk.BooleanVar(value=False)
        self.note = tk.StringVar(value="密钥留空表示不修改。" if app.store.has_api_key() else "还没有密钥。")
        pad = tk.Frame(self, bg=BG)
        pad.pack(fill="both", expand=True, padx=16, pady=16)
        self._row(pad, 0, "接口地址", self.base_var)
        self._row(pad, 1, "模型", self.model_var)
        self.key_entry = self._row(pad, 2, "API Key", self.key_var, show="*")
        tk.Checkbutton(pad, text="显示密钥", variable=self.show_var, command=self.toggle, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).grid(row=3, column=1, sticky="w")
        tk.Label(pad, text="使用快速回答，不开启深度思考。只发送作业状态或你写下的那段话，不发送账号密码。", bg=BG, fg=MUTED, font=FONT_SMALL, wraplength=420, justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 6))
        tk.Label(pad, textvariable=self.note, bg=BG, fg=WARN, font=FONT_SMALL, wraplength=420, justify="left").grid(row=5, column=0, columnspan=2, sticky="w")
        bar = tk.Frame(pad, bg=BG)
        bar.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(bar, text="保存", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(bar, text="清除密钥", style="Ghost.TButton", command=self.clear_key).pack(side="left", padx=8)
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        pad.columnconfigure(1, weight=1)
        center_on(self, app, 560, 340)
        self.deiconify()
        self.grab_set()

    def _row(self, parent, row: int, caption: str, variable: tk.StringVar, show: str = "") -> tk.Entry:
        tk.Label(parent, text=caption, bg=BG, fg=FG, font=FONT, width=10, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=5)
        entry = tk.Entry(parent, textvariable=variable, show=show, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.grid(row=row, column=1, sticky="ew", pady=5, ipady=4)
        return entry

    def toggle(self) -> None:
        self.key_entry.configure(show="" if self.show_var.get() else "*")

    def save(self) -> None:
        try:
            completions_url(self.base_var.get())
        except AskError as exc:
            messagebox.showwarning("DeepSeek", str(exc), parent=self)
            return
        typed = self.key_var.get().replace("\r", "").replace("\n", "").strip()
        try:
            self.app.store.set_api(self.base_var.get(), self.model_var.get(), typed or None)
        except SecretError as exc:
            messagebox.showerror("DeepSeek", str(exc), parent=self)
            return
        self.key_var.set("")
        self.note.set("已保存。")

    def clear_key(self) -> None:
        self.app.store.set_api(self.base_var.get(), self.model_var.get(), None, clear_key=True)
        self.key_var.set("")
        self.note.set("密钥已清除。")


class NoteWindow(tk.Toplevel):
    def __init__(self, app: "App", job: Job) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.job = job
        self.title(f"备注  {job.job_id}")
        self.configure(bg=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        tk.Label(self, text=job.name or job.job_id, bg=BG, fg=FG, font=("Microsoft YaHei UI", 13, "bold"), anchor="w", wraplength=420, justify="left").pack(fill="x", padx=16, pady=(14, 6))
        self.note = tk.Text(self, height=6, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT, padx=8, pady=6, wrap="word")
        self.note.pack(fill="both", expand=True, padx=16)
        self.note.insert("1.0", app.store.job_note(job.account_id, job.job_id))
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=12)
        ttk.Button(bar, text="保存", style="Accent.TButton", command=self._close).pack(side="left")
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        center_on(self, app, 480, 280)
        self.deiconify()
        self.note.focus_set()
        self.grab_set()

    def _close(self) -> None:
        self.app.store.set_job_note(self.job.account_id, self.job.job_id, self.note.get("1.0", "end").strip())
        if self.app.winfo_exists():
            self.app.redraw()
        self.destroy()


class DetailWindow(tk.Toplevel):
    def __init__(self, master: "App", job: Job, account_text: str) -> None:
        super().__init__(master)
        self.withdraw()
        self.title(f"{job.job_id}  {job.name}")
        self.configure(bg=BG)
        self.minsize(480, 360)
        try:
            self.attributes("-topmost", bool(master.attributes("-topmost")))
        except tk.TclError:
            pass
        shown = state_text(job.state)
        if job.state and shown != job.state:
            shown = f"{shown}    ({job.state})"
        rows = [
            ("账号", account_text),
            ("作业号", job.job_id),
            ("作业名", job.name),
            ("状态", shown),
            ("已运行", job.elapsed),
            ("排队时长", queue_text(job)),
            ("时限", job.timelimit),
            ("分区", job.partition),
            ("核数", job.cpus),
            ("内存", job.memory),
            ("节点/原因", job.place),
            ("提交时间", job.submit),
            ("开始时间", job.start),
            ("结束时间", job.end),
            ("退出码", job.exit_code),
            ("数据来源", job.source),
            ("工作目录", job.workdir),
        ]
        text = tk.Text(self, height=12, bg=CARD, fg=FG, relief="flat", font=FONT, padx=16, pady=12, wrap="word", highlightthickness=0)
        text.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        text.insert("1.0", "\n".join(f"{name}：{value or '—'}" for name, value in rows))
        text.configure(state="disabled")
        tk.Label(self, text="备注", bg=BG, fg=FG, font=FONT).pack(anchor="w", padx=16, pady=(10, 0))
        self.note = tk.Text(self, height=5, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT, padx=8, pady=6, wrap="word")
        self.note.pack(fill="x", padx=12, pady=(4, 0))
        self.note.insert("1.0", master.store.job_note(job.account_id, job.job_id))
        bar = ttk.Frame(self, style="App.TFrame")
        bar.pack(fill="x", padx=12, pady=12)
        body = "\n".join(f"{name}：{value}" for name, value in rows if value)
        ttk.Button(bar, text="保存备注", style="Accent.TButton", command=self._save_note).pack(side="left")
        ttk.Button(bar, text="复制全部", style="Ghost.TButton", command=lambda: self._copy(body)).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self._close).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._job = job
        center_on(self, master, 680, 520)
        self.deiconify()

    def _save_note(self) -> None:
        self.master.store.set_job_note(self._job.account_id, self._job.job_id, self.note.get("1.0", "end").strip())
        if self.master.winfo_exists():
            self.master.redraw()

    def _close(self) -> None:
        self._save_note()
        self.destroy()

    def _copy(self, body: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(body)


class TopWindow(tk.Toplevel):
    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.title("top")
        self.configure(bg=BG)
        self.minsize(640, 360)
        try:
            self.attributes("-topmost", bool(app.attributes("-topmost")))
        except tk.TclError:
            pass
        tk.Label(self, text="top", bg=BG, fg=FG, font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Label(self, text="只读取 top 的一屏快照。没有作业系统的机器，刷新时也会自动带上。", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=16, pady=(2, 8))
        self.box = tk.Text(self, wrap="none", bg=PANEL, fg=FG, relief="flat", font=("Consolas", 10), highlightthickness=0, padx=12, pady=10)
        self.box.pack(fill="both", expand=True, padx=16)
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=12)
        self.fetch_btn = ttk.Button(bar, text="重新读取", style="Accent.TButton", command=self.fetch)
        self.fetch_btn.pack(side="left")
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        cached = app.top_snapshot_text()
        self._show(cached or "正在读取当前账号的 top…")
        center_on(self, app, 860, 560)
        self.deiconify()
        if not cached:
            self.fetch()

    def _show(self, text: str) -> None:
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")

    def fetch(self) -> None:
        items = []
        for account in self.app.store.accounts():
            if self.app.account_filter not in {"all", account["id"]}:
                continue
            try:
                password = self.app.store.password(account["id"])
                error = ""
            except SecretError as exc:
                password = ""
                error = str(exc)
            items.append((account, password, error))
        if not items:
            self._show("先点「账号密码」，添加要查看的 Linux。")
            return
        self.fetch_btn.configure(state="disabled")
        self._show("正在读取 top…")
        known = self.app.store.known_hosts_path()

        def work() -> None:
            lines = []
            updates = []
            for account, password, error in items:
                name = self.app.tab_name(account["id"])
                if error or not password:
                    lines.append(f"【{name}】\n{error or '还没有填写密码。'}")
                    continue
                result = query_top({key: value for key, value in account.items() if key != "secret"}, password, known)
                updates.append((account["id"], result))
                lines.append(f"【{name}】\n{result.error or result.top_text or '没有输出。'}")
            self.after(0, lambda: self._done("\n\n".join(lines), updates))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, text: str, updates: list[tuple[str, AccountResult]]) -> None:
        if not self.winfo_exists():
            return
        self.fetch_btn.configure(state="normal")
        self._show(text)
        for account_id, result in updates:
            current = self.app.account_results.get(account_id)
            if current is None:
                self.app.account_results[account_id] = result
            else:
                current.top_text = result.top_text or current.top_text
                if result.error:
                    current.notice = result.error
        if self.app.winfo_exists():
            self.app.redraw()


class AccountDialog(tk.Toplevel):
    def __init__(self, master: "App", store: Store, on_changed) -> None:
        super().__init__(master)
        self.withdraw()
        self.store = store
        self.on_changed = on_changed
        self.editing_id: str | None = None
        self.ids: list[str] = []
        self.title("账号密码")
        self.configure(bg=BG)
        self.minsize(760, 460)
        self.transient(master)
        try:
            self.attributes("-topmost", bool(master.attributes("-topmost")))
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.label_var = tk.StringVar()
        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar(value="22")
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()
        self.extra_var = tk.StringVar()
        self.show_pass = tk.BooleanVar(value=False)
        self.note = tk.StringVar(value="选中左侧账号可修改，或点「新建」。")
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        tk.Label(left, text="账号1 到 账号n", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w")
        self.listbox = tk.Listbox(left, width=42, height=16, bg=CARD, fg=FG, selectbackground=ACCENT, selectforeground=palette.on_accent, relief="flat", highlightthickness=0, activestyle="none", exportselection=False, font=FONT)
        self.listbox.pack(fill="y", expand=True, pady=(6, 0))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        self._field(right, 0, "显示名", self.label_var)
        self.host_entry = self._field(right, 1, "主机", self.host_var)
        self._field(right, 2, "端口", self.port_var)
        self._field(right, 3, "用户名", self.user_var)
        self.pass_entry = self._field(right, 4, "密码", self.pass_var, show="*")
        tk.Checkbutton(right, text="显示密码", variable=self.show_pass, command=self.toggle_password, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).grid(row=5, column=1, sticky="w", pady=(0, 6))
        self._field(right, 6, "附加 PATH", self.extra_var)
        hint = "能用密码登录的 Linux 都可以加。有 Slurm 就看作业；没有作业系统时自动改看 top。密码只加密留在这台电脑。程序只查询，不提交也不取消。附加 PATH 可选，squeue 不在默认 PATH 时再填目录，多个用英文冒号，不要空格。修改时密码留空表示不改。"
        tk.Label(right, text=hint, bg=BG, fg=MUTED, font=FONT_SMALL, justify="left", wraplength=460).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 8))
        buttons = tk.Frame(right, bg=BG)
        buttons.grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Button(buttons, text="新建", style="Ghost.TButton", command=self.new_account).pack(side="left", padx=(0, 6), pady=4)
        ttk.Button(buttons, text="保存", style="Accent.TButton", command=self.save_account).pack(side="left", padx=(0, 6), pady=4)
        ttk.Button(buttons, text="删除", style="Ghost.TButton", command=self.delete_account).pack(side="left", padx=(0, 6), pady=4)
        self.test_btn = ttk.Button(buttons, text="测试连接", style="Ghost.TButton", command=self.test_connection)
        self.test_btn.pack(side="left", padx=(0, 6), pady=4)
        second = tk.Frame(right, bg=BG)
        second.grid(row=9, column=0, columnspan=2, sticky="w")
        ttk.Button(second, text="清除此主机旧密钥", style="Ghost.TButton", command=self.forget_key).pack(side="left", padx=(0, 6), pady=4)
        ttk.Button(second, text="打开配置目录", style="Ghost.TButton", command=self.open_folder).pack(side="left", pady=4)
        tk.Label(right, textvariable=self.note, bg=BG, fg=WARN, font=FONT_SMALL, justify="left", wraplength=460).grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.reload_list(prefer_first=True)
        if not self.ids:
            self.new_account()
            self.host_entry.focus_set()
        center_on(self, master, 880, 560)
        self.deiconify()
        self.grab_set()

    def _field(self, parent, row: int, caption: str, variable: tk.StringVar, show: str = "") -> tk.Entry:
        tk.Label(parent, text=caption, bg=BG, fg=FG, font=FONT, width=10, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=4)
        entry = tk.Entry(parent, textvariable=variable, show=show, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.grid(row=row, column=1, sticky="ew", pady=4, ipady=4)
        return entry

    def toggle_password(self) -> None:
        self.pass_entry.configure(show="" if self.show_pass.get() else "*")

    def reload_list(self, select_id: str | None = None, prefer_first: bool = False) -> None:
        self.listbox.unbind("<<ListboxSelect>>")
        self.listbox.delete(0, "end")
        self.ids = []
        for index, account in enumerate(self.store.accounts(), start=1):
            mark = "" if self.store.has_secret(account["id"]) else "  （无密码）"
            label = account.get("label") or account.get("username")
            self.listbox.insert("end", f"账号{index}  {label}  {account.get('username')}@{account.get('host')}:{account.get('port')}{mark}")
            self.ids.append(account["id"])
        target = select_id
        if target is None and prefer_first and self.ids:
            target = self.ids[0]
        if target in self.ids:
            index = self.ids.index(target)
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.listbox.see(index)
            self._load(target)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

    def on_select(self, _event=None) -> None:
        picked = self.listbox.curselection()
        if not picked:
            return
        self._load(self.ids[picked[0]])

    def _load(self, account_id: str) -> None:
        account = next((item for item in self.store.accounts() if item["id"] == account_id), None)
        if account is None:
            return
        self.editing_id = account_id
        self.label_var.set(account.get("label") or "")
        self.host_var.set(account.get("host") or "")
        self.port_var.set(str(account.get("port") or 22))
        self.user_var.set(account.get("username") or "")
        self.extra_var.set(account.get("extra_path") or "")
        self.pass_var.set("")
        self.note.set("密码留空表示不修改。" if self.store.has_secret(account_id) else "这个账号还没有密码。")

    def new_account(self) -> None:
        self.editing_id = None
        self.listbox.selection_clear(0, "end")
        self.label_var.set("")
        self.host_var.set("")
        self.port_var.set("22")
        self.user_var.set("")
        self.pass_var.set("")
        self.extra_var.set("")
        self.note.set("填写主机、端口、用户名和密码，然后点保存。主界面会按保存顺序显示为账号1、账号2。")

    def _collect(self) -> dict:
        host = self.host_var.get().strip()
        username = self.user_var.get().strip()
        port_text = self.port_var.get().strip() or "22"
        if not host or not username:
            raise ValueError("主机和用户名都要填。")
        if any(char.isspace() for char in host):
            raise ValueError("主机里不能有空格。")
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ValueError("端口要是 1 到 65535 的数字。")
        return {
            "id": self.editing_id or "",
            "label": self.label_var.get().strip() or username,
            "host": host,
            "port": int(port_text),
            "username": username,
            "extra_path": self.extra_var.get().strip(),
        }

    def _typed_password(self) -> str:
        return self.pass_var.get().replace("\r", "").replace("\n", "")

    def save_account(self) -> None:
        try:
            fields = self._collect()
        except ValueError as exc:
            messagebox.showwarning("账号", str(exc), parent=self)
            return
        try:
            new_id = self.store.upsert(fields, self._typed_password() or None)
        except SecretError as exc:
            messagebox.showerror("账号", str(exc), parent=self)
            return
        self.editing_id = new_id
        self.pass_var.set("")
        self.reload_list(select_id=new_id)
        self.note.set("已保存。")
        self.on_changed()

    def delete_account(self) -> None:
        if not self.editing_id:
            messagebox.showwarning("账号", "先在左侧选中要删除的账号。", parent=self)
            return
        if not messagebox.askyesno("删除账号", "只从这台电脑的列表里删除，不会动 Linux 上的账号。", parent=self):
            return
        self.store.delete(self.editing_id)
        self.editing_id = None
        self.new_account()
        self.reload_list(prefer_first=True)
        self.note.set("已删除。后面的账号会按新顺序重新编号。")
        self.on_changed()

    def forget_key(self) -> None:
        try:
            fields = self._collect()
        except ValueError as exc:
            messagebox.showwarning("账号", str(exc), parent=self)
            return
        removed = forget_host_key(self.store.known_hosts_path(), fields["host"], fields["port"])
        text = f"已清除 {fields['host']} 的 {removed} 条旧主机密钥。下次连接会重新记住。" if removed else "没有这台机器的旧主机密钥。"
        self.note.set(text)
        messagebox.showinfo("主机密钥", text, parent=self)

    def open_folder(self) -> None:
        os.startfile(self.store.folder)

    def test_connection(self) -> None:
        try:
            fields = self._collect()
        except ValueError as exc:
            messagebox.showwarning("账号", str(exc), parent=self)
            return
        typed = self._typed_password()
        if typed:
            password = typed
        elif self.editing_id and self.store.has_secret(self.editing_id):
            try:
                password = self.store.password(self.editing_id)
            except SecretError as exc:
                messagebox.showerror("账号", str(exc), parent=self)
                return
        else:
            messagebox.showwarning("账号", "先填写密码。测试连接不会替你保存，要留下请再点「保存」。", parent=self)
            return
        self.test_btn.configure(state="disabled")
        self.note.set("正在连接…")
        days = self.store.history_days()
        known = self.store.known_hosts_path()

        def work() -> None:
            result = query_account(fields, password, days, known)
            self.after(0, lambda: self._test_done(result))

        threading.Thread(target=work, daemon=True).start()

    def _test_done(self, result: AccountResult) -> None:
        if not self.winfo_exists():
            return
        self.test_btn.configure(state="normal")
        if result.error:
            self.note.set(result.error)
            messagebox.showerror("测试连接", result.error, parent=self)
            return
        lines = [f"已连上 {result.username}@{result.host}:{result.port}", f"当前 {len(result.jobs)} 个作业"]
        if result.fingerprint:
            lines.append(f"主机密钥 {result.fingerprint}")
        if result.notice:
            lines.append(result.notice)
        self.note.set("连接成功。")
        messagebox.showinfo("测试连接", "\n".join(lines), parent=self)


class UpdateDialog(tk.Toplevel):
    """Shows the new version and what changed, then hands off to the downloader."""

    def __init__(self, app: "App", offer) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.offer = offer
        self.title("发现新版本")
        self.configure(bg=BG)
        self.resizable(False, True)
        self.transient(app)
        tk.Frame(self, bg=OK, height=4).pack(fill="x")
        tk.Label(self, text=f"发现新版本 {offer.version}", bg=BG, fg=FG, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(self, text=f"当前版本 {VERSION}", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(0, 8))
        tk.Label(self, text="这一版改了什么", bg=BG, fg=FG, font=FONT).pack(anchor="w", padx=18)
        self.notes = tk.Text(self, height=10, wrap="word", bg=PANEL, fg=FG, relief="flat", font=FONT_SMALL, highlightthickness=1, highlightbackground=LINE, padx=10, pady=8)
        self.notes.pack(fill="both", expand=True, padx=18, pady=(4, 10))
        self.notes.insert("1.0", (offer.notes or "这个版本没有写更新说明。").strip()[:4000])
        self.notes.configure(state="disabled")
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(bar, text="现在更新", style="Accent.TButton", command=self.install).pack(side="left")
        ttk.Button(bar, text="稍后", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=8)
        ttk.Button(bar, text="跳过这个版本", style="Ghost.TButton", command=self.skip).pack(side="right")
        center_on(self, app, 560, 420)
        self.deiconify()
        self.grab_set()

    def install(self) -> None:
        self.destroy()
        self.app._start_download(self.offer)

    def skip(self) -> None:
        self.app.store.set_update_skipped(self.offer.version)
        try:
            self.app.update_btn.configure(text="检查更新")
        except tk.TclError:
            pass
        self.destroy()


class App(tk.Tk):
    def __init__(self, store: Store | None = None, user_name: str = "") -> None:
        _enable_dpi()
        super().__init__()
        self.store = store or Store()
        self.user_name = user_name
        self.restart_login = False
        palette.use(self.store.skin())
        sync_modules()
        i18n.language.code = i18n.resolve(self.store.language())
        i18n.install()
        self.alive = True
        self.busy = False
        self.pending_again = False
        self.jobs: list[Job] = []
        self.row_jobs: dict[str, Job] = {}
        self.brief_jobs: dict[str, list[Job]] = {key: [] for key, *_rest in BRIEF}
        self.account_results: dict[str, AccountResult] = {}
        self.filter = "all"
        self.sort_col: str | None = None
        self.sort_desc = False
        self.fail_count = 0
        self.empty_reason = NO_ACCOUNT
        self.last_stamp = ""
        self.next_at = time.monotonic() + REFRESH_SECONDS
        self.focus_key: tuple[str, str] | None = None
        self._note_after = None
        self._eat_release = False
        self._context_job: Job | None = None
        self.top_on = False
        self._in_ball = False
        self._ready = False
        self._tab_ids: list[str] | None = None
        self._tab_widgets: dict[str, tuple] = {}
        self.ask_open = False
        self.asking = False
        self.mode = "jobs"
        self.plan_popup = None
        if not self.store.plan_remind_at():
            self.store.touch_plan_remind()
        saved_tab = str(self.store.data.get("account_tab") or "all")
        known_ids = {account["id"] for account in self.store.accounts()}
        self.account_filter = saved_tab if saved_tab == "all" or saved_tab in known_ids else "all"
        self.view = self.store.view_mode()
        self.search_var = tk.StringVar()
        self.meta_var = tk.StringVar(value="还没有刷新")
        self.count_var = tk.StringVar(value="")
        self.ask_var = tk.StringVar()
        self.stat_vars = {key: tk.StringVar(value="0") for key, *_rest in BRIEF}
        self.always_on_top = bool(self.store.data.get("always_on_top"))
        self.title(self._window_title())
        self.configure(bg=BG)
        self.minsize(1040, 640)
        self._style()
        self._build()
        i18n.apply(self)
        self.ball = FloatBall(self)
        try:
            self.geometry(self.store.data.get("geometry") or "1180x720")
        except tk.TclError:
            self.geometry("1180x720")
        icon = _icon_file()
        if icon is not None:
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass
        self._apply_view()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.apply_text_style(self.store.text_family(), self.store.text_size(), save=False)
        self.bind("<F5>", lambda _event: self.refresh())
        self.bind("<Unmap>", self._on_unmap)
        self.report_callback_exception = self._on_callback_error
        self._ready = True
        self.redraw()
        self.after(400, self.refresh)
        self.after(1000, self.tick)
        self.after(1800, lambda: self.check_updates(silent=True))

    def _window_title(self, extra: str = "") -> str:
        who = f"  {self.user_name}" if self.user_name else ""
        base = f"{i18n.tr('作业看台')} {VERSION}{who}"
        return f"{base} - {extra}" if extra else base

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        exc.__traceback__ = tb
        _crash(exc)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)
        style.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG, borderwidth=0, rowheight=30, font=FONT)
        style.configure("Treeview.Heading", background=HEADING, foreground=FG, relief="flat", font=FONT)
        style.map("Treeview", background=[("selected", palette.pick)], foreground=[("selected", palette.on_accent)])
        style.configure("Accent.TButton", background=ACCENT, foreground=palette.on_accent, borderwidth=0, focuscolor=ACCENT, padding=(12, 6), font=FONT)
        style.map("Accent.TButton", background=[("pressed", palette.accent), ("active", palette.accent), ("disabled", palette.panel)], foreground=[("disabled", palette.muted)])
        style.configure("Ghost.TButton", background=PANEL, foreground=FG, borderwidth=0, focuscolor=PANEL, padding=(12, 6), font=FONT)
        style.map("Ghost.TButton", background=[("pressed", palette.line), ("active", palette.heading), ("disabled", palette.panel)], foreground=[("disabled", palette.muted)])
        style.configure("TCombobox", fieldbackground=palette.panel, background=palette.panel, foreground=palette.fg, arrowcolor=palette.fg, bordercolor=palette.line, lightcolor=palette.panel, darkcolor=palette.panel, selectbackground=palette.pick, selectforeground=palette.on_accent, padding=(6, 3))
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.panel), ("disabled", palette.card)],
            foreground=[("readonly", palette.fg), ("disabled", palette.muted)],
            background=[("readonly", palette.panel), ("active", palette.card), ("pressed", palette.heading)],
            arrowcolor=[("active", palette.accent), ("pressed", palette.accent)],
            selectbackground=[("readonly", palette.pick)],
            selectforeground=[("readonly", palette.on_accent)],
            bordercolor=[("focus", palette.accent)],
        )
        try:
            self.option_add("*TCombobox*Listbox.background", palette.panel)
            self.option_add("*TCombobox*Listbox.foreground", palette.fg)
            self.option_add("*TCombobox*Listbox.selectBackground", palette.pick)
            self.option_add("*TCombobox*Listbox.selectForeground", palette.on_accent)
            self.option_add("*TCombobox*Listbox.font", FONT)
        except tk.TclError:
            pass
        style.configure("TScrollbar", background=palette.sash, troughcolor=palette.panel, bordercolor=palette.panel, arrowcolor=palette.fg, borderwidth=0, relief="flat", arrowsize=12)
        style.map("TScrollbar", background=[("active", palette.accent), ("pressed", palette.accent)])
        self._paint_combobox_popdowns()
        if hasattr(self, "tree"):
            self._recolor_tags()
        if hasattr(self, "brief_shells"):
            self._style_brief()
        if hasattr(self, "top_box"):
            self.top_box.configure(bg=PANEL, fg=FG)

    def _paint_combobox_popdowns(self) -> None:
        """ttk gives every dropdown its own listbox; repaint the ones already built."""

        def walk(node) -> None:
            if isinstance(node, ttk.Combobox):
                try:
                    popdown = str(node.tk.call("ttk::combobox::PopdownWindow", node))
                    listing = f"{popdown}.f.l"
                    node.tk.call(
                        listing,
                        "configure",
                        "-background",
                        palette.panel,
                        "-foreground",
                        palette.fg,
                        "-selectbackground",
                        palette.pick,
                        "-selectforeground",
                        palette.on_accent,
                    )
                except tk.TclError:
                    pass
            try:
                children = node.winfo_children()
            except tk.TclError:
                return
            for child in children:
                walk(child)

        try:
            walk(self)
        except tk.TclError:
            pass

    def open_text_style(self) -> None:
        win = tk.Toplevel(self)
        win.withdraw()
        win.title("文字")
        win.configure(bg=BG)
        win.resizable(True, True)
        win.minsize(360, 420)
        win.transient(self)
        family = tk.StringVar(value=self.store.text_family())
        size = tk.IntVar(value=self.store.text_size())
        pad = tk.Frame(win, bg=BG)
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        tk.Label(pad, text="字体", bg=BG, fg=FG, font=FONT).pack(anchor="w")
        for key, label in TEXT_CHOICES:
            tk.Radiobutton(pad, text=label, variable=family, value=key, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT, anchor="w").pack(fill="x", pady=1)
        tk.Label(pad, text="字号", bg=BG, fg=FG, font=FONT).pack(anchor="w", pady=(10, 0))
        sizes = tk.Frame(pad, bg=BG)
        sizes.pack(fill="x", pady=(4, 0))
        for index, (value, label) in enumerate(TEXT_SIZES):
            tk.Radiobutton(sizes, text=label, variable=size, value=value, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT, anchor="w").grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 12), pady=2)
        sizes.columnconfigure(0, weight=1)
        sizes.columnconfigure(1, weight=1)

        def use() -> None:
            self.apply_text_style(family.get(), int(size.get()))
            win.destroy()

        bar = tk.Frame(pad, bg=BG)
        bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="用这个", style="Accent.TButton", command=use).pack(side="left")
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=win.destroy).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.update_idletasks()
        center_on(win, self, max(420, win.winfo_reqwidth() + 28), max(420, win.winfo_reqheight() + 20))
        win.deiconify()
        win.focus_set()

    def apply_text_style(self, family: str, size: int, save: bool = True) -> None:
        import plans as plans_module

        if save:
            self.store.set_text_style(family, size)
        apply_text(self, self.store.text_family() if save else family, self.store.text_size() if save else size)
        global FONT, FONT_SMALL, FONT_TITLE
        FONT = (text_look.family, text_look.size)
        FONT_SMALL = (text_look.family, max(8, text_look.size - 1))
        FONT_TITLE = (text_look.family, text_look.size + 8, "bold")
        plans_module.FONT = FONT
        plans_module.FONT_SMALL = FONT_SMALL
        if hasattr(self, "refresh_btn"):
            self._style()

    def open_language_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0)
        current = self.store.language()
        for key, label in i18n.LANGUAGES:
            mark = "" if current == key else ""
            menu.add_command(label=(label + mark), command=lambda name=key: self.apply_language(name))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def apply_language(self, choice: str) -> None:
        self.store.set_language(choice)
        i18n.language.code = i18n.resolve(choice)
        i18n.apply(self)
        self.title(self._window_title())
        self.redraw()

    def open_skin_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for key, spec in SKINS.items():
            mark = "    当前" if key == palette.name else ""
            menu.add_command(label=spec["label"] + mark, command=lambda name=key: self.apply_skin(name))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def apply_skin(self, name: str) -> None:
        self.store.set_skin(name)
        palette.use(name)
        sync_modules()
        self._style()
        self.configure(bg=BG)
        restyle(self)
        self._style_panes()
        self._recolor_tags()
        self.redraw()
        if hasattr(self, "plan_board"):
            self.plan_board.reload()

    def _style_brief(self) -> None:
        for key, shell in self.brief_shells.items():
            bg = getattr(palette, f"{key}_bg")
            fg = getattr(palette, f"{key}_fg")
            head, title, count = self.brief_heads[key]
            shell.configure(bg=bg, highlightbackground=LINE)
            head.configure(bg=bg)
            title.configure(bg=bg, fg=_bucket_ink(key))
            count.configure(bg=bg, fg=fg)
            self.brief_boxes[key].configure(bg=bg, fg=fg, selectbackground=palette.pick, selectforeground=palette.on_accent)

    def _style_panes(self) -> None:
        options = {"bg": palette.sash, "sashrelief": "flat", "sashwidth": 7, "bd": 0, "sashpad": 0}
        for pane in (getattr(self, "body_pane", None), getattr(self, "brief_paned", None)):
            if pane is not None:
                pane.configure(**options)

    def _recolor_tags(self) -> None:
        if not hasattr(self, "tree"):
            return
        self.tree.tag_configure("run", background=palette.run_bg, foreground=palette.run_fg)
        self.tree.tag_configure("wait", background=palette.wait_bg, foreground=palette.wait_fg)
        self.tree.tag_configure("done", background=palette.bg, foreground=palette.done_fg)
        self.tree.tag_configure("bad", background=palette.bad_bg, foreground=palette.bad_fg)
        self.tree.tag_configure("other", background=palette.bg, foreground=palette.fg)
        if not hasattr(self, "status"):
            return
        self.status.tag_configure("ok", foreground=OK)
        self.status.tag_configure("warn", foreground=WARN)
        self.status.tag_configure("bad", foreground=BAD)
        self.status.tag_configure("muted", foreground=MUTED)

    def logout(self) -> None:
        self.restart_login = True
        self.on_close()

    def _build(self) -> None:
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")
        outer = ttk.Frame(self, style="App.TFrame", padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)
        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        who = f"    {self.user_name}" if self.user_name else ""
        ttk.Label(header, text=f"{i18n.tr('作业看台')}  {VERSION}{who}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Linux 作业，和自己要做的事。只查询，不提交也不取消。", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        nav = ttk.Frame(header, style="App.TFrame")
        nav.pack(fill="x", pady=(10, 0))
        self.jobs_mode_btn = ttk.Button(nav, text="作业", command=lambda: self.set_mode("jobs"))
        self.jobs_mode_btn.pack(side="left", padx=(0, 6))
        self.plans_mode_btn = ttk.Button(nav, text="管家", command=lambda: self.set_mode("plans"))
        self.plans_mode_btn.pack(side="left", padx=(0, 6))
        ttk.Button(nav, text="账号密码", style="Accent.TButton", command=self.open_accounts).pack(side="left", padx=(0, 12))
        self.brief_btn = ttk.Button(nav, text="简洁", command=lambda: self.set_view("brief"))
        self.brief_btn.pack(side="left", padx=(0, 4))
        self.full_btn = ttk.Button(nav, text="完整", command=lambda: self.set_view("full"))
        self.full_btn.pack(side="left", padx=(0, 8))
        self.refresh_btn = ttk.Button(nav, text="立即刷新", style="Accent.TButton", command=self.refresh)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        ttk.Button(nav, text="悬浮球", style="Ghost.TButton", command=self.minimize_to_ball).pack(side="left", padx=(0, 10))
        self.hide_done = tk.BooleanVar(value=bool(self.store.data.get("hide_done_jobs")))
        self.hide_bad = tk.BooleanVar(value=bool(self.store.data.get("hide_bad_jobs")))
        tk.Checkbutton(nav, text="隐藏完成", variable=self.hide_done, command=self.toggle_hide, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).pack(side="left")
        tk.Checkbutton(nav, text="隐藏报错", variable=self.hide_bad, command=self.toggle_hide, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).pack(side="left", padx=(4, 0))
        ttk.Button(nav, text="退出登录", style="Ghost.TButton", command=self.logout).pack(side="right")
        ttk.Button(nav, text="皮肤", style="Ghost.TButton", command=self.open_skin_menu).pack(side="right", padx=(0, 6))
        ttk.Button(nav, text="语言", style="Ghost.TButton", command=self.open_language_menu).pack(side="right", padx=(0, 6))
        ttk.Button(nav, text="文字", style="Ghost.TButton", command=self.open_text_style).pack(side="right", padx=(0, 6))
        self.update_btn = ttk.Button(nav, text="检查更新", style="Ghost.TButton", command=self.check_updates)
        self.update_btn.pack(side="right", padx=(0, 6))

        tab_row = ttk.Frame(outer, style="App.TFrame")
        self.tab_row = tab_row
        tab_row.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        tab_row.columnconfigure(0, weight=1)
        self.tab_canvas = tk.Canvas(tab_row, height=62, bg=BG, highlightthickness=0)
        self.tab_canvas.grid(row=0, column=0, sticky="ew")
        self.tab_frame = tk.Frame(self.tab_canvas, bg=BG)
        self.tab_window = self.tab_canvas.create_window((0, 0), window=self.tab_frame, anchor="nw")
        self.tab_frame.bind("<Configure>", lambda _event: self.tab_canvas.configure(scrollregion=self.tab_canvas.bbox("all")))
        self.tab_canvas.bind("<MouseWheel>", lambda event: self.tab_canvas.xview_scroll(int(-event.delta / 120), "units"))
        ttk.Label(tab_row, text="运行 / 排队 / 完成 / 报错", style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(8, 0))

        stats = ttk.Frame(outer, style="App.TFrame")
        self.stats = stats
        stats.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        for index, (key, title) in enumerate(BRIEF):
            stats.columnconfigure(index, weight=1)
            card = tk.Frame(stats, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=14, pady=10, cursor="hand2")
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 8, 0))
            name = tk.Label(card, text=title, bg=CARD, fg=MUTED, font=FONT_SMALL, cursor="hand2")
            name.pack(anchor="w")
            value = tk.Label(card, textvariable=self.stat_vars[key], bg=CARD, fg=_bucket_ink(key), font=("Microsoft YaHei UI", 22, "bold"), cursor="hand2")
            value.pack(anchor="w")
            for widget in (card, name, value):
                widget.bind("<Button-1>", lambda _event, name=key: self.on_stat(name))

        self.banner = tk.Label(outer, text="", bg=palette.wait_bg, fg=palette.wait_fg, font=FONT_SMALL, anchor="w", padx=10, pady=6)
        tool = ttk.Frame(outer, style="App.TFrame")
        self.tool = tool
        tool.grid(row=4, column=0, sticky="ew", pady=(10, 8))
        self.filter_bar = ttk.Frame(tool, style="App.TFrame")
        self.filter_bar.pack(side="left")
        self.filter_buttons: dict[str, ttk.Button] = {}
        for key, title in FILTERS:
            button = ttk.Button(self.filter_bar, text=title, style="Ghost.TButton", command=lambda name=key: self.set_filter(name))
            button.pack(side="left", padx=(0, 6))
            self.filter_buttons[key] = button
        self.top_on = False
        self.top_btn = ttk.Button(self.filter_bar, text="top", style="Ghost.TButton", command=self.toggle_top)
        self.top_btn.pack(side="left", padx=(0, 6))
        self.search_caption = ttk.Label(tool, text="搜索", style="Muted.TLabel")
        self.search_caption.pack(side="left", padx=(8, 4))
        search = tk.Entry(tool, textvariable=self.search_var, width=18, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        search.pack(side="left", ipady=3)
        self.search_var.trace_add("write", lambda *_args: self.redraw())
        ttk.Label(tool, text="结束作业近", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.days_box = ttk.Combobox(tool, width=4, state="readonly", values=("1", "3", "7", "14", "30"))
        self.days_box.set(str(self.store.history_days()))
        self.days_box.pack(side="left")
        self.days_box.bind("<<ComboboxSelected>>", self.on_days)
        ttk.Label(tool, text="天", style="Muted.TLabel").pack(side="left", padx=(4, 0))
        self.later_btn = ttk.Button(tool, text="稍后", style="Ghost.TButton", command=self.open_later)
        meta = ttk.Frame(tool, style="App.TFrame")
        meta.pack(side="right")
        ttk.Label(meta, textvariable=self.meta_var, style="Muted.TLabel").pack(side="left", padx=(0, 12))
        ttk.Label(meta, textvariable=self.count_var, style="Muted.TLabel").pack(side="left")

        self.body_pane = tk.PanedWindow(outer, orient="vertical", bg=palette.sash, sashwidth=7, sashrelief="flat", opaqueresize=True, bd=0, sashpad=0)
        self.body_pane.grid(row=5, column=0, sticky="nsew")
        self.main = ttk.Frame(self.body_pane, style="App.TFrame")
        self.main.rowconfigure(0, weight=1)
        self.main.columnconfigure(0, weight=1)
        self.brief = tk.Frame(self.main, bg=BG)
        self.brief.grid(row=0, column=0, sticky="nsew")
        self.brief.rowconfigure(0, weight=1)
        self.brief.columnconfigure(0, weight=1)
        self.brief_paned = tk.PanedWindow(self.brief, orient="horizontal", bg=palette.sash, sashwidth=7, sashrelief="flat", opaqueresize=True, bd=0, sashpad=0)
        self.brief_paned.grid(row=0, column=0, sticky="nsew")
        self.brief_boxes: dict[str, tk.Listbox] = {}
        self.brief_shells: dict[str, tk.Frame] = {}
        self.brief_heads = {}
        for _index, (key, title) in enumerate(BRIEF):
            bg = getattr(palette, f"{key}_bg")
            fg = getattr(palette, f"{key}_fg")
            shell = tk.Frame(self.brief_paned, bg=bg, highlightthickness=1, highlightbackground=LINE)
            shell.rowconfigure(1, weight=1)
            shell.columnconfigure(0, weight=1)
            head = tk.Frame(shell, bg=bg, padx=12, pady=8)
            head.grid(row=0, column=0, sticky="ew")
            title_label = tk.Label(head, text=title, bg=bg, fg=_bucket_ink(key), font=("Microsoft YaHei UI", 12, "bold"))
            title_label.pack(side="left")
            count_label = tk.Label(head, textvariable=self.stat_vars[key], bg=bg, fg=fg, font=("Microsoft YaHei UI", 16, "bold"))
            count_label.pack(side="right")
            self.brief_heads[key] = (head, title_label, count_label)
            box = tk.Listbox(shell, bg=bg, fg=fg, selectbackground=palette.pick, selectforeground=palette.on_accent, relief="flat", highlightthickness=0, activestyle="none", exportselection=False, font=FONT)
            box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
            box.bind("<ButtonRelease-1>", lambda event, name=key: self.on_brief_click(name, event))
            box.bind("<Double-1>", lambda _event, name=key: self.on_brief_double(name))
            box.bind("<Return>", lambda _event, name=key: self.on_brief_double(name))
            box.bind("<Button-3>", lambda event, name=key: self.on_brief_menu(name, event))
            box.bind("<MouseWheel>", lambda event, widget=box: widget.yview_scroll(int(-event.delta / 120), "units"))
            self.brief_boxes[key] = box
            self.brief_shells[key] = shell
        self._layout_brief_panes()

        self.table = ttk.Frame(self.main, style="App.TFrame")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.rowconfigure(0, weight=1)
        self.table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(self.table, columns=[item[0] for item in COLUMNS], show="headings", selectmode="browse")
        ybar = ttk.Scrollbar(self.table, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(self.table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        for cid, title, width, stretch in COLUMNS:
            self.tree.heading(cid, text=title, command=lambda column=cid: self.on_sort(column))
            self.tree.column(cid, width=width, minwidth=48, stretch=stretch, anchor="w")
        self.tree.tag_configure("run", background=palette.run_bg, foreground=palette.run_fg)
        self.tree.tag_configure("wait", background=palette.wait_bg, foreground=palette.wait_fg)
        self.tree.tag_configure("done", background=palette.bg, foreground=palette.done_fg)
        self.tree.tag_configure("bad", background=palette.bad_bg, foreground=palette.bad_fg)
        self.tree.tag_configure("other", background=palette.bg, foreground=palette.fg)
        self.tree.bind("<ButtonRelease-1>", self.on_tree_click)
        self.tree.bind("<Double-1>", self.on_tree_double)
        self.tree.bind("<Return>", self.on_tree_double)
        self.tree.bind("<Button-3>", self.on_right)
        self.tree.bind("<MouseWheel>", lambda event: self.tree.yview_scroll(int(-event.delta / 120), "units"))
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="查看详情", command=self.on_open)
        self.menu.add_command(label="写备注", command=self.note_selected)
        self.menu.add_command(label="进入命令行", command=self.shell_selected)
        self.menu.add_command(label="复制作业号", command=self.copy_id)
        self.menu.add_command(label="复制作业名", command=self.copy_name)
        self.menu.add_command(label="删除这条", command=self.dismiss_selected)
        self._delete_index = self.menu.index("end")
        self.empty = tk.Label(self.main, text=NO_ACCOUNT, bg=BG, fg=MUTED, font=("Microsoft YaHei UI", 12), justify="center")
        self.top_panel = tk.Frame(self.main, bg=CARD, highlightthickness=1, highlightbackground=LINE)
        tk.Label(self.top_panel, text="top", bg=CARD, fg=FG, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        self.top_box = tk.Text(self.top_panel, height=14, wrap="none", bg=PANEL, fg=FG, relief="flat", font=("Consolas", 9), highlightthickness=0, padx=10, pady=8)
        self.top_box.pack(fill="both", expand=True, padx=8, pady=8)
        self.top_box.configure(state="disabled")
        self._build_setup()

        self.status_wrap = tk.Frame(self.body_pane, bg=BG)
        self.status = tk.Text(self.status_wrap, height=4, wrap="word", bg=BG, fg=MUTED, relief="flat", font=FONT_SMALL, highlightthickness=0, padx=2, pady=4, takefocus=0, cursor="arrow")
        self.status.pack(fill="both", expand=True)
        self.body_pane.add(self.main, stretch="always", minsize=220)
        self.body_pane.add(self.status_wrap, minsize=48, height=96)
        self.status.tag_configure("ok", foreground=OK)
        self.status.tag_configure("warn", foreground=WARN)
        self.status.tag_configure("bad", foreground=BAD)
        self.status.tag_configure("muted", foreground=MUTED)
        self.status.configure(state="disabled")
        self._set_status([("muted", "点「账号密码」填写主机、端口、用户名和密码。还没有账号时，表格中间也可以直接填。")])

        self.ask_frame = tk.Frame(outer, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=10, pady=8)
        tk.Label(self.ask_frame, text="问 DeepSeek", bg=CARD, fg=FG, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        tk.Label(self.ask_frame, text="按当前账号和搜索结果提问。只发送作业状态，不发送密码。", bg=CARD, fg=MUTED, font=FONT_SMALL).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(self.ask_frame, bg=CARD)
        row.pack(fill="x")
        ask_entry = tk.Entry(row, textvariable=self.ask_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        ask_entry.pack(side="left", fill="x", expand=True, ipady=4)
        ask_entry.bind("<Return>", lambda _event: self.send_question())
        self.ask_btn = ttk.Button(row, text="发送", style="Accent.TButton", command=self.send_question)
        self.ask_btn.pack(side="left", padx=(8, 0))
        self.answer = tk.Text(self.ask_frame, height=6, wrap="word", bg=PANEL, fg=FG, relief="flat", font=FONT, highlightthickness=0, padx=8, pady=6)
        self.answer.pack(fill="x", pady=(8, 0))
        self.answer.insert("1.0", "例如：哪些报错了？排队的原因是什么？")
        self.answer.configure(state="disabled")
        self.plan_board = PlanBoard(outer, self)
        self._paint_later()
        self._paint_view_buttons()
        self._paint_mode()

    def _build_setup(self) -> None:
        self.setup_host = tk.StringVar()
        self.setup_port = tk.StringVar(value="22")
        self.setup_user = tk.StringVar()
        self.setup_pass = tk.StringVar()
        self.setup_label = tk.StringVar()
        self.setup_extra = tk.StringVar()
        self.setup_note = tk.StringVar(value="密码只加密留在这台电脑。显示名和附加 PATH 可以空着。")
        self.setup = tk.Frame(self.main, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=22, pady=18)
        tk.Label(self.setup, text="填写 Linux 账号", bg=CARD, fg=FG, font=("Microsoft YaHei UI", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        fields = (
            (1, "主机", self.setup_host, ""),
            (2, "端口", self.setup_port, ""),
            (3, "用户名", self.setup_user, ""),
            (4, "密码", self.setup_pass, "*"),
            (5, "显示名", self.setup_label, ""),
            (6, "附加 PATH", self.setup_extra, ""),
        )
        for row, caption, variable, show in fields:
            tk.Label(self.setup, text=caption, bg=CARD, fg=FG, font=FONT, width=10, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=4)
            tk.Entry(
                self.setup,
                textvariable=variable,
                show=show,
                width=32,
                bg=PANEL,
                fg=FG,
                insertbackground=FG,
                relief="flat",
                font=FONT,
                highlightthickness=1,
                highlightbackground=LINE,
                highlightcolor=ACCENT,
            ).grid(row=row, column=1, sticky="ew", pady=4, ipady=4)
        tk.Label(self.setup, textvariable=self.setup_note, bg=CARD, fg=MUTED, font=FONT_SMALL, wraplength=420, justify="left").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 8))
        buttons = tk.Frame(self.setup, bg=CARD)
        buttons.grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Button(buttons, text="保存账号", style="Accent.TButton", command=self.save_setup).pack(side="left")
        ttk.Button(buttons, text="打开账号窗口", style="Ghost.TButton", command=self.open_accounts).pack(side="left", padx=(8, 0))
        self.setup.columnconfigure(1, weight=1)

    def popup_parent(self):
        if self._in_ball and self.ball.winfo_exists():
            return self.ball
        return self

    def _paint_pin(self) -> None:
        return

    def _layout_brief_panes(self) -> None:
        current = list(self.brief_paned.panes())
        for pane in current:
            self.brief_paned.forget(pane)
        for key, _title in BRIEF:
            if key == "done" and self.hide_done.get():
                continue
            if key == "bad" and self.hide_bad.get():
                continue
            self.brief_paned.add(self.brief_shells[key], stretch="always", minsize=100)

    def toggle_hide(self) -> None:
        self.store.data["hide_done_jobs"] = bool(self.hide_done.get())
        self.store.data["hide_bad_jobs"] = bool(self.hide_bad.get())
        self.store.save()
        self._layout_brief_panes()
        self.redraw()

    def _paint_view_buttons(self) -> None:
        self.brief_btn.configure(style="Accent.TButton" if self.view == "brief" else "Ghost.TButton")
        self.full_btn.configure(style="Accent.TButton" if self.view == "full" else "Ghost.TButton")

    def _paint_mode(self) -> None:
        due = len(due_plans(self.store.plans(), date.today()))
        self.jobs_mode_btn.configure(style="Accent.TButton" if self.mode == "jobs" else "Ghost.TButton")
        self.plans_mode_btn.configure(text=f"管家 {due}" if due else "管家", style="Accent.TButton" if self.mode == "plans" else "Ghost.TButton")

    def set_mode(self, mode: str) -> None:
        if mode not in {"jobs", "plans"}:
            return
        self.mode = mode
        if mode == "plans":
            self.store.touch_plan_remind()
            self.tab_row.grid_remove()
            self.stats.grid_remove()
            if self.banner.winfo_ismapped():
                self.banner.grid_remove()
            self.tool.grid_remove()
            self.body_pane.grid_remove()
            if self.ask_frame.winfo_ismapped():
                self.ask_frame.grid_remove()
            self.plan_board.grid(row=1, column=0, rowspan=6, sticky="nsew")
            self.plan_board.reload()
        else:
            if self.plan_board.winfo_ismapped():
                self.plan_board.grid_remove()
            self.tab_row.grid(row=1, column=0, sticky="ew", pady=(12, 0))
            self.stats.grid(row=2, column=0, sticky="ew", pady=(10, 0))
            self.tool.grid(row=4, column=0, sticky="ew", pady=(10, 8))
            self.body_pane.grid(row=5, column=0, sticky="nsew")
            self._update_banner()
            if self.ask_open:
                self.ask_frame.grid(row=7, column=0, sticky="ew", pady=(8, 0))
            self.redraw()
        self._paint_mode()

    def refresh_plan_badge(self) -> None:
        if self.winfo_exists():
            self._paint_mode()

    def focus_plans(self) -> None:
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        self.restore_from_ball()
        self.set_mode("plans")
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def maybe_plan_remind(self) -> None:
        popup = self.plan_popup
        if popup is not None:
            try:
                if popup.winfo_exists():
                    return
            except tk.TclError:
                pass
            self.plan_popup = None
        minutes = self.store.plan_remind_minutes()
        if minutes <= 0 or self.mode == "plans":
            return
        if time.time() - self.store.plan_remind_at() < minutes * 60:
            return
        items = due_plans(self.store.plans(), date.today())
        if not items:
            return
        self.store.touch_plan_remind()
        self.plan_popup = PlanRemind(self, items)

    def save_setup(self) -> None:
        host = self.setup_host.get().strip()
        username = self.setup_user.get().strip()
        port_text = self.setup_port.get().strip() or "22"
        if not host or not username:
            self.setup_note.set("主机和用户名都要填。")
            return
        if any(char.isspace() for char in host):
            self.setup_note.set("主机里不能有空格。")
            return
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            self.setup_note.set("端口要是 1 到 65535 的数字。")
            return
        password = self.setup_pass.get().replace("\r", "").replace("\n", "")
        try:
            existing = next(
                (
                    item
                    for item in self.store.accounts()
                    if (item.get("host") or "") == host
                    and (item.get("username") or "") == username
                    and int(item.get("port") or 0) == int(port_text)
                ),
                None,
            )
            self.store.upsert(
                {
                    "id": existing["id"] if existing else "",
                    "label": self.setup_label.get().strip() or username,
                    "host": host,
                    "port": int(port_text),
                    "username": username,
                    "extra_path": self.setup_extra.get().strip(),
                },
                password or None,
            )
        except SecretError as exc:
            self.setup_note.set(str(exc))
            return
        self.setup_pass.set("")
        self.setup_host.set("")
        self.setup_user.set("")
        self.setup_label.set("")
        self.setup_extra.set("")
        self.setup_port.set("22")
        self.setup_note.set("已保存。下一个账号点上方「账号密码」。")
        self.redraw()
        self.refresh()

    def _paint_later(self) -> None:
        count = len(self.store.later_keys())
        if count:
            self.later_btn.configure(text=f"稍后 {count}")
            if not self.later_btn.winfo_ismapped():
                self.later_btn.pack(side="left", padx=(8, 0))
        elif self.later_btn.winfo_ismapped():
            self.later_btn.pack_forget()

    def toggle_pin(self) -> None:
        self.always_on_top = not self.always_on_top
        self.attributes("-topmost", self.always_on_top)
        self.store.data["always_on_top"] = self.always_on_top
        self.store.save()
        self._paint_pin()

    def set_view(self, mode: str) -> None:
        if mode not in {"brief", "full"}:
            return
        if mode != self.view:
            self.view = mode
            self.store.set_view_mode(mode)
        if mode == "brief" and self.top_on:
            self.top_on = False
            self.top_btn.configure(style="Ghost.TButton")
        self._paint_view_buttons()
        self._apply_view()
        self.redraw()

    def _apply_view(self) -> None:
        if self.view == "brief":
            self.table.grid_remove()
            self.brief.grid()
            if self.filter_bar.winfo_ismapped():
                self.filter_bar.pack_forget()
        else:
            self.brief.grid_remove()
            self.table.grid()
            if not self.filter_bar.winfo_ismapped():
                self.filter_bar.pack(side="left", before=self.search_caption)

    def on_stat(self, name: str) -> None:
        if name == "done" and self.hide_done.get():
            self.hide_done.set(False)
        if name == "bad" and self.hide_bad.get():
            self.hide_bad.set(False)
        self.store.data["hide_done_jobs"] = bool(self.hide_done.get())
        self.store.data["hide_bad_jobs"] = bool(self.hide_bad.get())
        self.store.save()
        self._layout_brief_panes()
        self.filter = name
        self._style_filters()
        if self.view != "full":
            self.set_view("full")
        else:
            self.redraw()

    def check_updates(self, silent: bool = False) -> None:
        if getattr(self, "_updating", False):
            return
        if not silent and not update_url():
            from tkinter import simpledialog

            typed = simpledialog.askstring(
                "更新地址",
                "填写 GitHub 仓库地址（例如 https://github.com/你的名字/jobdesk），\n"
                "或者一份 json 清单的 https 地址。",
                parent=self,
            )
            if not typed or not str(typed).strip():
                return
            typed = str(typed).strip()
            if not (typed.startswith("https://") or typed.startswith("github:")):
                tell(self, "更新", "更新地址要以 https:// 开头，或者写成 github:owner/repo。")
                return
            save_update_url(typed)
        self._updating = True
        self.store.touch_update_check()

        def work() -> None:
            found = None
            error = ""
            try:
                found = look_for_update(VERSION)
            except UpdateError as exc:
                error = str(exc)
            except Exception as exc:
                error = f"检查没有完成：{exc}"
            self.after(0, lambda item=found, problem=error: self._show_update(item, problem, silent))

        threading.Thread(target=work, daemon=True).start()

    def _show_update(self, found, error: str, silent: bool) -> None:
        self._updating = False
        if not self.winfo_exists():
            return
        if error:
            if not silent:
                tell(self, "更新", error)
            return
        if found is None:
            try:
                self.update_btn.configure(text="检查更新")
            except tk.TclError:
                pass
            if not silent:
                tell(self, "更新", f"已经是最新版本 {VERSION}。")
            return
        if silent and found.version == self.store.update_skipped():
            return
        try:
            self.update_btn.configure(text=f"更新 {found.version}")
        except tk.TclError:
            pass
        UpdateDialog(self, found)

    def _start_download(self, found) -> None:
        self._updating = True

        def work() -> None:
            path = None
            problem = ""
            try:
                path = download_release(found.url, found.sha256, found.size)
            except UpdateError as exc:
                problem = str(exc)
            except Exception as exc:
                problem = f"下载没有完成：{exc}"
            self.after(0, lambda item=path, text=problem: self._finish_download(item, text))

        threading.Thread(target=work, daemon=True).start()

    def _finish_download(self, path, problem: str) -> None:
        self._updating = False
        if not self.winfo_exists():
            return
        if problem or path is None:
            tell(self, "更新", problem or "下载没有完成。")
            return
        try:
            launch_swap(path, os.getpid())
        except UpdateError as exc:
            tell(self, "更新", str(exc))
            return
        self.on_close()

    def on_close(self) -> None:
        self.alive = False
        try:
            if not self._in_ball:
                self.store.data["geometry"] = self.geometry()
            self.store.save()
        except Exception:
            pass
        try:
            self.ball.destroy()
        except Exception:
            pass
        self.destroy()

    def _on_unmap(self, event) -> None:
        if event.widget is not self or self._in_ball or not self.alive:
            return
        try:
            iconic = self.state() == "iconic"
        except tk.TclError:
            return
        if iconic:
            self.after(40, lambda: self.minimize_to_ball(from_unmap=True))

    def minimize_to_ball(self, from_unmap: bool = False) -> None:
        if not self.alive or self._in_ball:
            return
        if from_unmap:
            # The 40ms delay can outlive a quick restore; only hide if still iconic.
            try:
                if self.state() != "iconic":
                    return
            except tk.TclError:
                return
        self._in_ball = True
        try:
            self.store.data["geometry"] = self.geometry()
            self.store.save()
        except Exception:
            pass
        run, wait, done = self.ball_numbers()
        self.withdraw()
        self.ball.show(run, wait, done)
    def restore_from_ball(self) -> None:
        if not self._in_ball:
            try:
                self.deiconify()
                self.state("normal")
                self.lift()
            except tk.TclError:
                pass
            return
        self._in_ball = False
        self.ball.hide()
        self.deiconify()
        try:
            self.state("normal")
        except tk.TclError:
            pass
        self.lift()
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def ball_numbers(self) -> tuple[int, int, int]:
        run, wait, done, _bad = self._counts_for(None)
        return run, wait, done

    def ball_detail(self) -> str:
        run, wait, done, bad = self._counts_for(None)
        lines = [f"运行 {run}    排队 {wait}", f"完成 {done}    报错 {bad}"]
        for account in self.store.accounts():
            one_run, one_wait, one_done, one_bad = self._counts_for(account["id"])
            if one_run + one_wait + one_done + one_bad == 0 and account["id"] not in self.account_results:
                continue
            lines.append(f"{self.tab_name(account['id'])}  运行{one_run} 排队{one_wait} 完成{one_done} 报错{one_bad}")
        return "\n".join(lines)

    def toggle_top(self) -> None:
        if self.view != "full":
            self.set_view("full")
        self.top_on = not self.top_on
        self.top_btn.configure(style="Accent.TButton" if self.top_on else "Ghost.TButton")
        if not self.top_on:
            self.redraw()
            return
        if self._scoped_tops():
            self.redraw()
            return
        self._show_top_text("正在读取 top…")
        self._fetch_top()

    def _show_top_text(self, text: str) -> None:
        self.brief.grid_remove()
        self.table.grid_remove()
        self.top_box.configure(state="normal")
        self.top_box.delete("1.0", "end")
        self.top_box.insert("1.0", text)
        self.top_box.configure(state="disabled")
        self.top_panel.grid(row=0, column=0, sticky="nsew")
        self.main.rowconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=0)

    def _fetch_top(self) -> None:
        items = []
        for account in self.store.accounts():
            if self.account_filter not in {"all", account["id"]}:
                continue
            try:
                password = self.store.password(account["id"])
                error = ""
            except SecretError as exc:
                password = ""
                error = str(exc)
            items.append((account, password, error))
        if not items:
            self._show_top_text("先添加账号，再看 top。")
            return
        known = self.store.known_hosts_path()

        def work() -> None:
            lines = []
            updates = []
            for account, password, error in items:
                name = self.tab_name(account["id"])
                if error or not password:
                    lines.append(f"【{name}】\n{error or '还没有填写密码。'}")
                    continue
                result = query_top({key: value for key, value in account.items() if key != "secret"}, password, known)
                updates.append((account["id"], result))
                lines.append(f"【{name}】\n{result.error or result.top_text or '没有输出。'}")
            text = "\n\n".join(lines)
            self.after(0, lambda: self._top_ready(text, updates))

        threading.Thread(target=work, daemon=True).start()

    def _top_ready(self, text: str, updates: list[tuple[str, AccountResult]]) -> None:
        for account_id, result in updates:
            current = self.account_results.get(account_id)
            if current is None:
                self.account_results[account_id] = result
            else:
                current.top_text = result.top_text or current.top_text
        if not self.alive or not self.top_on:
            return
        self._show_top_text(text or "没有输出。")

    def top_snapshot_text(self) -> str:
        rows = self._scoped_tops()
        if not rows:
            return ""
        return "\n\n".join(f"【{name}】\n{text}" for name, text in rows)

    def _scoped_tops(self) -> list[tuple[str, str]]:
        rows = []
        for account in self.store.accounts():
            if self.account_filter not in {"all", account["id"]}:
                continue
            result = self.account_results.get(account["id"])
            if result and result.top_text and not result.error:
                rows.append((self.tab_name(account["id"]), result.top_text))
        return rows

    def _paint_top(self, _nothing: bool, rows: list[tuple[str, str]]) -> None:
        if not self.top_on:
            if self.top_panel.winfo_ismapped():
                self.top_panel.grid_remove()
            self.main.rowconfigure(0, weight=1)
            self.main.rowconfigure(1, weight=0)
            if self.view == "brief" and not self.brief.winfo_ismapped():
                self._apply_view()
            elif self.view == "full" and not self.table.winfo_ismapped():
                self._apply_view()
            return
        if not rows:
            return
        body = "\n\n".join(f"【{name}】\n{text}" for name, text in rows)
        self._show_top_text(body)

    def open_accounts(self) -> None:
        AccountDialog(self, self.store, self.refresh)

    def open_settings(self) -> None:
        SettingsDialog(self)

    def open_later(self) -> None:
        LaterWindow(self)

    def toggle_ask(self) -> None:
        self.ask_open = not self.ask_open
        if self.ask_open:
            self.ask_frame.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        else:
            self.ask_frame.grid_remove()

    def set_filter(self, name: str) -> None:
        if self.top_on:
            self.top_on = False
            self.top_btn.configure(style="Ghost.TButton")
        self.filter = name
        self._style_filters()
        self.redraw()

    def _style_filters(self) -> None:
        for key, button in self.filter_buttons.items():
            button.configure(style="Accent.TButton" if key == self.filter else "Ghost.TButton")

    def on_days(self, _event=None) -> None:
        try:
            days = int(self.days_box.get())
        except ValueError:
            return
        if days == self.store.history_days():
            return
        self.store.set_history_days(days)
        self.refresh()

    def on_sort(self, column: str) -> None:
        if self.sort_col == column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = column
            self.sort_desc = column in {"elapsed", "submit", "job_id"}
        self.redraw()

    def tick(self) -> None:
        if not self.alive:
            return
        if not self.busy:
            remain = self.next_at - time.monotonic()
            if remain <= 0:
                self.refresh()
            else:
                minutes, seconds = divmod(int(remain), 60)
                self.count_var.set(f"下次自动刷新 {minutes:02d}:{seconds:02d}")
        if not self.busy and not getattr(self, "_updating", False):
            if time.time() - self.store.update_last_check() > UPDATE_CHECK_HOURS * 3600:
                self.check_updates(silent=True)
        self.maybe_plan_remind()
        self.after(1000, self.tick)

    def refresh(self) -> None:
        if not self.alive:
            return
        if self.busy:
            self.pending_again = True
            return
        accounts = self.store.accounts()
        self.count_var.set("正在刷新…")
        self.meta_var.set("正在连接各账号…")
        if not accounts:
            self.jobs = []
            self.account_results = {}
            self.fail_count = 0
            self.empty_reason = NO_ACCOUNT
            self.next_at = time.monotonic() + REFRESH_SECONDS
            self.last_stamp = ""
            self.meta_var.set("还没有账号")
            self.title(self._window_title())
            self._set_status([("muted", "还没有账号。点上方「账号密码」，或在中间的卡片里填写主机、端口、用户名和密码。")])
            self._update_banner()
            self.redraw()
            return
        self.busy = True
        self.refresh_btn.configure(state="disabled")
        items = []
        for index, account in enumerate(accounts):
            public = {key: value for key, value in account.items() if key != "secret"}
            try:
                password = self.store.password(account["id"])
                error = ""
            except SecretError as exc:
                password = ""
                error = str(exc)
            items.append((index, public, password, error))
        days = self.store.history_days()
        known = self.store.known_hosts_path()

        def work() -> None:
            results = self._fetch(items, days, known)
            self.after(0, lambda got=results: self._apply(got))

        threading.Thread(target=work, daemon=True).start()

    def _fetch(self, items, days: int, known) -> list[AccountResult]:
        results: list[AccountResult | None] = [None] * len(items)
        pending = []
        for index, account, password, error in items:
            base = AccountResult(
                label=account.get("label") or account.get("username") or "账号",
                username=account.get("username") or "",
                host=account.get("host") or "",
                port=int(account.get("port") or 22),
                account_id=str(account.get("id") or ""),
            )
            if error or not password:
                base.error = error or "还没有填写密码。"
                results[index] = base
            else:
                pending.append((index, account, password))
        if pending:
            with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
                futures = {pool.submit(query_account, account, password, days, known): (index, account) for index, account, password in pending}
                for future in as_completed(futures):
                    index, account = futures[future]
                    try:
                        results[index] = future.result()
                    except Exception as exc:
                        results[index] = AccountResult(
                            label=account.get("label") or account.get("username") or "账号",
                            username=account.get("username") or "",
                            host=account.get("host") or "",
                            port=int(account.get("port") or 22),
                            error=f"读取失败：{one_line(str(exc))}",
                            account_id=str(account.get("id") or ""),
                        )
        return [item for item in results if item is not None]

    def _apply(self, results: list[AccountResult]) -> None:
        if not self.alive:
            return
        self.busy = False
        self.refresh_btn.configure(state="normal")
        again = self.pending_again
        self.pending_again = False
        self.jobs = []
        lines = []
        fails = 0
        setup_gaps = 0
        self.account_results = {}
        accounts = self.store.accounts()
        for index, result in enumerate(results):
            account_id = result.account_id or (accounts[index]["id"] if index < len(accounts) else "")
            if account_id:
                self.account_results[account_id] = result
            title = self.tab_name(account_id) if account_id else result.label
            if result.error:
                if _setup_gap(result.error):
                    setup_gaps += 1
                    lines.append(("warn", f"{title}  {result.username}@{result.host}:{result.port}  {result.error}"))
                else:
                    fails += 1
                    lines.append(("bad", f"{title}  {result.username}@{result.host}:{result.port}  {result.error}"))
                continue
            self.jobs.extend(result.jobs)
            run, wait, done, bad = self._count_jobs(result.jobs)
            note = f"  {result.notice}" if result.notice else ""
            lines.append(("ok", f"{title}  {result.username}@{result.host}:{result.port}  运行 {run}，排队 {wait}，完成 {done}，报错 {bad}{note}"))
        self.fail_count = fails
        if not self.jobs and setup_gaps and fails == 0:
            self.empty_reason = "账号已经在列表里，但还没有密码。\n点「账号密码」补上密码并保存。"
        elif not self.jobs and fails:
            self.empty_reason = "没有读到作业。\n原因在窗口最下面。"
        elif not self.jobs:
            self.empty_reason = f"近 {self.store.history_days()} 天没有作业。"
        else:
            self.empty_reason = "没有符合当前筛选的作业。"
        previous = self.store.job_buckets()
        fresh = finished_since(previous, [job for job in self.jobs if self._shown(job)])
        self.store.set_job_buckets(next_buckets(previous, self.jobs))
        self.last_stamp = time.strftime("%H:%M:%S")
        self.meta_var.set(f"上次刷新 {self.last_stamp}")
        self.next_at = time.monotonic() + REFRESH_SECONDS
        self.title(self._window_title("" if fails == 0 else f"{fails} 个账号未连上"))
        self._set_status(lines or [("muted", "没有账号结果。")])
        self._update_banner()
        self.redraw()
        if fresh:
            self.after(80, lambda batch=list(fresh): self._announce(batch))
        if again:
            self.refresh()

    def _announce(self, jobs: list[Job]) -> None:
        if not self.alive or not jobs:
            return
        DonePopup(self, jobs)

    def _update_banner(self) -> None:
        if self.mode != "jobs":
            if self.banner.winfo_ismapped():
                self.banner.grid_remove()
            return
        if self.account_filter != "all":
            result = self.account_results.get(self.account_filter)
            text = result.error if result and result.error else ""
        else:
            failed = [item for item in self.account_results.values() if item.error and not _setup_gap(item.error)]
            missing = [item for item in self.account_results.values() if item.error and _setup_gap(item.error)]
            parts = []
            if failed:
                parts.append(f"{len(failed)} 个账号没连上")
            if missing:
                parts.append(f"{len(missing)} 个账号还没有密码")
            text = "，".join(parts)
        if text:
            self.banner.configure(text="  " + text, bg=palette.wait_bg, fg=palette.wait_fg)
            self.banner.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        elif self.banner.winfo_ismapped():
            self.banner.grid_remove()

    def _set_status(self, lines: list[tuple[str, str]]) -> None:
        self.status.configure(state="normal")
        self.status.delete("1.0", "end")
        for index, (tag, text) in enumerate(lines):
            if index:
                self.status.insert("end", "\n")
            self.status.insert("end", i18n.tr(text), tag)
        self.status.configure(state="disabled")

    def tab_name(self, account_id: str) -> str:
        for index, account in enumerate(self.store.accounts(), start=1):
            if account["id"] == account_id:
                return f"账号{index}"
        return "账号"

    def display_account(self, job: Job) -> str:
        tab = self.tab_name(job.account_id)
        label = (job.account_label or "").strip()
        if label and label not in tab:
            return f"{tab} {label}"
        return tab

    def _counts_for(self, account_id: str | None) -> tuple[int, int, int, int]:
        if account_id in (None, "all"):
            jobs = self.jobs
        else:
            jobs = [job for job in self.jobs if job.account_id == account_id]
        return self._count_jobs(jobs)

    def _count_jobs(self, jobs: list[Job]) -> tuple[int, int, int, int]:
        run = wait = done = bad = 0
        for job in jobs:
            if not self._shown(job):
                continue
            bucket = job_bucket(job)
            if bucket in {"run", "other"}:
                run += 1
            elif bucket == "wait":
                wait += 1
            elif bucket == "done":
                done += 1
            elif bucket == "bad":
                bad += 1
        return run, wait, done, bad

    def _shown(self, job: Job) -> bool:
        return job_key(job) not in self.store.dismissed_jobs()

    def scoped_jobs(self) -> list[Job]:
        jobs = self.jobs
        if self.account_filter != "all":
            jobs = [job for job in jobs if job.account_id == self.account_filter]
        return [job for job in jobs if self._search_hit(job) and self._shown(job)]

    def _search_hit(self, job: Job) -> bool:
        query = self.search_var.get().strip().casefold()
        if not query:
            return True
        blob = " ".join([self.display_account(job), job.username, job.job_id, job.name, job.state, state_text(job.state), job.place, job.partition]).casefold()
        return query in blob

    def _passes_filter(self, job: Job) -> bool:
        bucket = job_bucket(job)
        if bucket == "other":
            bucket = "run"
        if self.hide_done.get() and bucket == "done":
            return False
        if self.hide_bad.get() and bucket == "bad":
            return False
        if self.filter in {"", "all"}:
            return True
        return bucket == self.filter

    def sync_tabs(self) -> None:
        ids = ["all"] + [account["id"] for account in self.store.accounts()]
        if self._tab_ids != ids:
            self._tab_ids = ids
            if self.account_filter not in ids:
                self.account_filter = "all"
            self._rebuild_tabs()
        self._update_tab_styles()

    def _rebuild_tabs(self) -> None:
        for child in self.tab_frame.winfo_children():
            child.destroy()
        self._tab_widgets = {}
        self._add_tab("all")
        for account in self.store.accounts():
            self._add_tab(account["id"])

    def _add_tab(self, key: str) -> None:
        frame = tk.Frame(self.tab_frame, bg=PANEL, padx=12, pady=6, cursor="hand2", highlightthickness=1, highlightbackground=LINE)
        title = tk.Label(frame, text=self._tab_title(key), bg=PANEL, fg=FG, font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2")
        sub = tk.Label(frame, text="", bg=PANEL, fg=MUTED, font=FONT_SMALL, cursor="hand2")
        title.pack(anchor="w")
        sub.pack(anchor="w")
        frame.pack(side="left", padx=(0, 8), pady=2)
        for widget in (frame, title, sub):
            widget.bind("<Button-1>", lambda _event, name=key: self.select_account(name))
            widget.bind("<Button-3>", lambda event, name=key: self.on_tab_menu(name, event))
        self._tab_widgets[key] = (frame, title, sub)

    def on_tab_menu(self, key: str, event) -> None:
        if key == "all":
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="进入命令行", command=lambda name=key: self.open_account_shell(name))
        self._tab_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _tab_title(self, key: str) -> str:
        if key == "all":
            return "全部"
        for index, account in enumerate(self.store.accounts(), start=1):
            if account["id"] == key:
                label = (account.get("label") or "").strip()
                username = account.get("username") or ""
                if label and label != username:
                    return f"账号{index}  {label}"
                return f"账号{index}"
        return "账号"

    def _tab_subtitle(self, key: str) -> str:
        if key == "all":
            run, wait, done, bad = self._counts_for(None)
            return f"{run + wait + done + bad} 个作业"
        result = self.account_results.get(key)
        if result and result.error:
            return "无密码" if _setup_gap(result.error) else "未连上"
        if result and result.top_text and not result.jobs:
            return "top"
        run, wait, done, bad = self._counts_for(key)
        return f"{run} / {wait} / {done} / {bad}"

    def _update_tab_styles(self) -> None:
        for key, (frame, title, sub) in self._tab_widgets.items():
            selected = key == self.account_filter
            bg = ACCENT if selected else PANEL
            fg = palette.on_accent if selected else FG
            result = None if key == "all" else self.account_results.get(key)
            if result and result.error and not selected:
                sub_fg = BAD
            else:
                sub_fg = palette.fg if selected else MUTED
            edge = ACCENT if selected else LINE
            frame.configure(bg=bg, highlightbackground=edge)
            title.configure(bg=bg, fg=fg, text=self._tab_title(key))
            sub.configure(bg=bg, fg=sub_fg, text=self._tab_subtitle(key))

    def select_account(self, key: str) -> None:
        self.account_filter = key
        self.store.data["account_tab"] = key
        self.store.save()
        self._update_banner()
        self._update_tab_styles()
        self.redraw()

    def redraw(self) -> None:
        if not self._ready:
            return
        self.sync_tabs()
        scoped = self.scoped_jobs()
        run, wait, done, bad = self._count_jobs(scoped)
        self.stat_vars["run"].set(str(run))
        self.stat_vars["wait"].set(str(wait))
        self.stat_vars["done"].set(str(done))
        self.stat_vars["bad"].set(str(bad))
        self._fill_brief(scoped)
        self._fill_tree(scoped)
        tops = self._scoped_tops()
        self._paint_top(not scoped, tops)
        self._show_empty(not scoped and not tops)
        if self._in_ball:
            run, wait, done = self.ball_numbers()
            self.ball.render(run, wait, done)
        self._paint_later()

    def _fill_brief(self, jobs: list[Job]) -> None:
        grouped = {key: [] for key, *_rest in BRIEF}
        for job in jobs:
            bucket = job_bucket(job)
            if bucket == "other":
                bucket = "run"
            if bucket in grouped:
                grouped[bucket].append(job)
        for key, _title in BRIEF:
            rows = grouped[key]
            rows.sort(key=lambda job: job.submit or "", reverse=True)
            box = self.brief_boxes[key]
            box.delete(0, "end")
            self.brief_jobs[key] = rows
            for job in rows:
                box.insert("end", self._brief_line(job))
            focus = self.focus_key
            if focus:
                for index, job in enumerate(rows):
                    if (job.account_id, job.job_id) == focus:
                        box.selection_set(index)
                        box.see(index)

    def _job_title(self, job: Job) -> str:
        note = one_line(self.store.job_note(job.account_id, job.job_id), 42)
        name = job.name or "未命名"
        return f"{name}  {note}" if note else name

    def _elapsed_cell(self, job: Job) -> str:
        """Pending jobs have no elapsed time; show how long they have been queued."""
        if job_bucket(job) == "wait":
            waited = queue_text(job)
            return f"排 {waited}" if waited else "排队中"
        return job.elapsed or "—"

    def _brief_line(self, job: Job) -> str:
        who = "" if self.account_filter != "all" else self.display_account(job) + "  "
        bucket = job_bucket(job)
        place = one_line(job.place, 28)
        extra = f"  {place}" if place and bucket != "done" else ""
        return f"{who}{state_text(job.state)}  {self._job_title(job)}   {job.job_id}   {self._elapsed_cell(job)}{extra}"

    def _fill_tree(self, jobs: list[Job]) -> None:
        selected_key = self.focus_key
        if selected_key is None:
            selected = self.tree.selection()
            if selected:
                current = self.row_jobs.get(selected[0])
                if current is not None:
                    selected_key = (current.account_id, current.job_id)
        yview = self.tree.yview()
        rows = list(jobs)
        if self.view == "full":
            rows = [job for job in rows if self._passes_filter(job)]
        counts = {key: 0 for key, _title in FILTERS}
        for job in jobs:
            bucket = job_bucket(job)
            if bucket == "other":
                bucket = "run"
            if self.hide_done.get() and bucket == "done":
                continue
            if self.hide_bad.get() and bucket == "bad":
                continue
            counts["all"] += 1
            if bucket in counts:
                counts[bucket] += 1
        for key, title in FILTERS:
            self.filter_buttons[key].configure(text=f"{title} {counts[key]}")
        self._style_filters()
        if self.sort_col:
            rows.sort(key=lambda job: _column_value(self.sort_col or "", job), reverse=self.sort_desc)
        else:
            rows.sort(key=lambda job: job.submit or "", reverse=True)
            rows.sort(key=lambda job: {"run": 0, "wait": 1, "other": 2, "bad": 3, "done": 4}.get(job_bucket(job), 5))
        for cid, title, _width, _stretch in COLUMNS:
            mark = " ↓" if self.sort_col == cid and self.sort_desc else " ↑" if self.sort_col == cid else ""
            self.tree.heading(cid, text=title + mark, command=lambda column=cid: self.on_sort(column))
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        self.row_jobs = {}
        restore = None
        for index, job in enumerate(rows):
            iid = f"row-{index}"
            self.row_jobs[iid] = job
            self.tree.insert(
                "",
                "end",
                iid=iid,
                tags=(kind(job.state),),
                values=(
                    self.display_account(job),
                    job.job_id,
                    self._job_title(job),
                    state_text(job.state),
                    self._elapsed_cell(job),
                    job.timelimit,
                    job.partition,
                    job.cpus,
                    job.memory,
                    job.place,
                    short_time(job.submit),
                ),
            )
            if selected_key == (job.account_id, job.job_id):
                restore = iid
        if restore:
            self.tree.selection_set(restore)
            self.tree.focus(restore)
            self.tree.see(restore)
        elif yview:
            self.tree.yview_moveto(yview[0])
        if self.focus_key and restore:
            self.focus_key = None

    def _show_empty(self, nothing: bool) -> None:
        if self.store.accounts() or not nothing:
            self.setup.place_forget()
        if not nothing:
            self.empty.place_forget()
            return
        if not self.store.accounts():
            self.empty.place_forget()
            self.setup.place(relx=0.5, rely=0.46, anchor="center")
            self.setup.lift()
            return
        if self.busy and not self.jobs:
            text = "正在读取各账号的作业…"
        elif self.jobs and self.search_var.get().strip():
            text = "没有符合搜索的作业。"
        elif self.jobs and self.view == "full" and self.filter != "all":
            text = "这一类里没有作业。"
        elif self.jobs:
            text = "这个账号下没有符合条件的作业。"
        else:
            text = self.empty_reason
        self.empty.configure(text=text)
        self.empty.place(relx=0.5, rely=0.46, anchor="center")
        self.empty.lift()

    def selected_job(self) -> Job | None:
        selected = self.tree.selection()
        if not selected:
            return None
        return self.row_jobs.get(selected[0])

    def _brief_job(self, name: str) -> Job | None:
        box = self.brief_boxes[name]
        picked = box.curselection()
        rows = self.brief_jobs.get(name) or []
        if not picked or picked[0] >= len(rows):
            return None
        return rows[picked[0]]

    def _cancel_note(self) -> None:
        if self._note_after is not None:
            self.after_cancel(self._note_after)
            self._note_after = None

    def _schedule_note(self, job: Job) -> None:
        if job_bucket(job) != "run":
            return
        self._cancel_note()
        self._note_after = self.after(400, lambda item=job: self._open_scheduled_note(item))

    def _open_scheduled_note(self, job: Job) -> None:
        self._note_after = None
        self.open_note(job)

    def on_brief_click(self, name: str, event=None) -> None:
        if self._eat_release:
            self._eat_release = False

    def on_brief_double(self, name: str) -> None:
        self._eat_release = True
        self._cancel_note()
        job = self._brief_job(name)
        if job is not None:
            self.open_note(job)

    def on_brief_menu(self, name: str, event) -> None:
        box = self.brief_boxes[name]
        index = box.nearest(event.y)
        rows = self.brief_jobs.get(name) or []
        if index < 0 or index >= len(rows):
            return
        box.selection_clear(0, "end")
        box.selection_set(index)
        self._context_job = rows[index]
        self._prepare_menu(self._context_job)
        self.menu.tk_popup(event.x_root, event.y_root)

    def on_tree_click(self, event) -> None:
        if self._eat_release:
            self._eat_release = False
            return
        row = self.tree.identify_row(event.y)
        return

    def on_tree_double(self, event=None) -> None:
        self._eat_release = True
        self._cancel_note()
        job = None
        if event is not None and hasattr(event, "y"):
            row = self.tree.identify_row(event.y)
            job = self.row_jobs.get(row) if row else None
        if job is None:
            job = self.selected_job()
        if job is not None:
            self.open_note(job)

    def open_job(self, job: Job) -> None:
        self.open_note(job)

    def open_note(self, job: Job) -> None:
        NoteWindow(self, job)

    def open_shell(self, job: Job) -> None:
        account = next((item for item in self.store.accounts() if item["id"] == job.account_id), None)
        if account is None:
            tell(self, "命令行", "这个账号已经不在列表里。")
            return
        try:
            password = self.store.password(job.account_id)
        except SecretError as exc:
            tell(self, "命令行", str(exc))
            return
        if not password:
            tell(self, "命令行", "先在「账号密码」里填写这个账号的密码。")
            return
        ShellWindow(self, job, account, password)

    def open_account_shell(self, account_id: str) -> None:
        account = next((item for item in self.store.accounts() if item["id"] == account_id), None)
        if account is None:
            tell(self, "命令行", "这个账号已经不在列表里。")
            return
        try:
            password = self.store.password(account_id)
        except SecretError as exc:
            tell(self, "命令行", str(exc))
            return
        if not password:
            tell(self, "命令行", "先在「账号密码」里填写这个账号的密码。")
            return
        home = Job(
            job_id="",
            name="",
            state="",
            elapsed="",
            timelimit="",
            partition="",
            cpus="",
            memory="",
            place="",
            submit="",
            start="",
            end="",
            exit_code="",
            source="",
            account_id=account_id,
            account_label=(account.get("label") or "").strip(),
            username=account.get("username") or "",
            host=account.get("host") or "",
            port=int(account.get("port") or 22),
        )
        ShellWindow(self, home, account, password)

    def _menu_job(self) -> Job | None:
        if self._context_job is not None:
            return self._context_job
        return self.selected_job()

    def on_open(self, _event=None) -> None:
        job = self._menu_job()
        if job is not None:
            DetailWindow(self, job, self.display_account(job))

    def note_selected(self) -> None:
        job = self._menu_job()
        if job is not None:
            self.open_note(job)

    def shell_selected(self) -> None:
        job = self._menu_job()
        if job is None:
            return
        self.open_shell(job)

    def on_right(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        self._context_job = self.row_jobs.get(row)
        self._prepare_menu(self._context_job)
        self.menu.tk_popup(event.x_root, event.y_root)

    def _prepare_menu(self, job: Job | None) -> None:
        state = "normal" if job is not None else "disabled"
        self.menu.entryconfigure(self._delete_index, label="不再显示这条", state=state)

    def dismiss_selected(self) -> None:
        job = self._menu_job()
        if job is None:
            return
        self.store.dismiss_job(job_key(job))
        self.drop_later(job)
        self.redraw()

    def copy_id(self) -> None:
        job = self._menu_job()
        if job is None:
            return
        self.clipboard_clear()
        self.clipboard_append(job.job_id)
        self.meta_var.set(f"上次刷新 {self.last_stamp}    已复制作业号 {job.job_id}".strip())

    def copy_name(self) -> None:
        job = self._menu_job()
        if job is None:
            return
        self.clipboard_clear()
        self.clipboard_append(job.name)
        self.meta_var.set(f"上次刷新 {self.last_stamp}    已复制作业名 {job.name}".strip())

    def show_job(self, job: Job) -> None:
        self.drop_later(job)
        self.restore_from_ball()
        if job.account_id:
            self.account_filter = job.account_id
            self.store.data["account_tab"] = job.account_id
            self.store.save()
        self.filter = "all"
        self.focus_key = (job.account_id, job.job_id)
        self._update_banner()
        self.redraw()
        DetailWindow(self, job, self.display_account(job))

    def defer(self, job: Job) -> None:
        keys = self.store.later_keys()
        key = job_key(job)
        if key not in keys:
            keys.append(key)
        self.store.set_later_keys(keys)
        self._paint_later()

    def drop_later(self, job: Job) -> None:
        key = job_key(job)
        keys = [item for item in self.store.later_keys() if item != key]
        if len(keys) != len(self.store.later_keys()):
            self.store.set_later_keys(keys)
            self._paint_later()

    def later_jobs(self) -> tuple[list[Job], list[str]]:
        by_key = {job_key(job): job for job in self.jobs}
        found = []
        missing = []
        for key in self.store.later_keys():
            job = by_key.get(key)
            if job is None:
                missing.append(key)
            else:
                found.append(job)
        return found, missing

    def send_question(self) -> None:
        if self.asking:
            return
        question = self.ask_var.get().strip()
        if not question:
            self._set_answer("先写一个问题。")
            return
        if not self.store.has_api_key():
            self._set_answer("先点左上角「DeepSeek」，填写 API Key。")
            return
        try:
            key = self.store.api_key()
        except SecretError as exc:
            self._set_answer(str(exc))
            return
        self.asking = True
        self.ask_btn.configure(state="disabled")
        self._set_answer("正在问…")
        named = [replace(job, account_label=self.display_account(job)) for job in self.scoped_jobs()]
        errors = []
        accounts = self.store.accounts()
        for account in accounts:
            if self.account_filter not in {"all", account["id"]}:
                continue
            result = self.account_results.get(account["id"])
            if result and result.error:
                errors.append(f"{self.tab_name(account['id'])} {result.error}")
        context = snapshot_text(named, errors)
        base = self.store.api_base()
        model = self.store.api_model()

        def work() -> None:
            try:
                answer = ask_deepseek(base, key, model, question, context)
            except AskError as exc:
                answer = str(exc)
            except Exception as exc:
                answer = f"询问失败：{one_line(str(exc))}"
            self.after(0, lambda text=answer: self._finish_ask(text))

        threading.Thread(target=work, daemon=True).start()

    def _finish_ask(self, text: str) -> None:
        self.asking = False
        if self.winfo_exists():
            self.ask_btn.configure(state="normal")
            self._set_answer(text)

    def _set_answer(self, text: str) -> None:
        self.answer.configure(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", text)
        self.answer.configure(state="disabled")


def login_dialog(owner) -> tuple[Store, str] | None:
    """Login on the real window. A hidden parent made password typing stutter."""
    result: dict = {}
    win = owner
    win.title("登录")
    win.configure(bg=palette.bg)
    win.resizable(False, False)
    card = tk.Frame(win, bg=palette.card, padx=18, pady=16)
    card.pack(fill="both", expand=True, padx=18, pady=18)
    tk.Label(card, text="作业看台", bg=palette.card, fg=palette.fg, font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    tk.Label(card, text="每个用户有自己的作业账号和便利贴。", bg=palette.card, fg=palette.muted, font=FONT_SMALL).pack(anchor="w", pady=(4, 8))
    if legacy_waiting():
        tk.Label(card, text="第一个注册的用户，会用上这台电脑里已经保存的账号和便利贴。", bg=palette.card, fg=palette.muted, font=FONT_SMALL, wraplength=340, justify="left").pack(anchor="w", pady=(0, 8))
    name_var = tk.StringVar(value=last_user_name())
    message = tk.StringVar()
    tk.Label(card, text="用户名", bg=palette.card, fg=palette.muted, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(6, 2))
    tk.Entry(card, textvariable=name_var, bg=palette.panel, fg=palette.fg, insertbackground=palette.fg, relief="flat", font=FONT, highlightthickness=1, highlightbackground=palette.line, highlightcolor=palette.accent).pack(fill="x", ipady=4)
    tk.Label(card, text="密码", bg=palette.card, fg=palette.muted, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(6, 2))
    password_box = tk.Entry(card, show="*", bg=palette.panel, fg=palette.fg, insertbackground=palette.fg, relief="flat", font=("Consolas", 12), width=32, exportselection=False, highlightthickness=1, highlightbackground=palette.line, highlightcolor=palette.accent)
    password_box.pack(fill="x", ipady=4)
    tk.Label(card, textvariable=message, bg=palette.card, fg=palette.bad, font=FONT_SMALL, wraplength=340, justify="left").pack(fill="x", pady=(8, 0))
    bar = tk.Frame(card, bg=palette.card)
    bar.pack(fill="x", pady=(12, 0))
    busy = {"on": False}
    ticket = {"n": 0}
    done = tk.IntVar(master=win, value=0)

    def set_busy(active: bool) -> None:
        busy["on"] = active
        state = "disabled" if active else "normal"
        login_btn.configure(state=state)
        register_btn.configure(state=state)

    def leave(_event=None) -> None:
        ticket["n"] += 1
        try:
            done.set(1)
        except tk.TclError:
            pass

    def accept(register: bool) -> None:
        if busy["on"]:
            return
        name = name_var.get().strip()
        password = password_box.get()
        problem = _check_login(name, password)
        if problem:
            message.set(problem)
            return
        set_busy(True)
        message.set("正在核对…")
        ticket["n"] += 1
        token = ticket["n"]
        box: queue.Queue = queue.Queue(maxsize=1)

        def work() -> None:
            user_id = ""
            err = ""
            try:
                if register:
                    user_id = register_user(name, password)
                else:
                    user_id = check_user(name, password)
                    if not user_id:
                        err = "用户名或密码不对。没有账号时先点注册。"
            except ValueError as exc:
                err = str(exc)
            except Exception as exc:
                err = f"登录没有完成：{exc}"
            try:
                box.put_nowait((user_id, err))
            except queue.Full:
                pass

        def poll(started: float) -> None:
            if token != ticket["n"] or not win.winfo_exists():
                return
            try:
                user_id, err = box.get_nowait()
            except queue.Empty:
                if time.monotonic() - started >= 20:
                    ticket["n"] += 1
                    set_busy(False)
                    message.set("核对太久了，请再试一次。关闭窗口可以退出。")
                    return
                win.after(100, lambda: poll(started))
                return
            set_busy(False)
            if err or not user_id:
                message.set(err or "用户名或密码不对。没有账号时先点注册。")
                return
            result["store"] = Store(user_folder(user_id))
            result["name"] = name
            done.set(1)

        threading.Thread(target=work, daemon=True).start()
        win.after(100, lambda: poll(time.monotonic()))

    login_btn = tk.Button(bar, text="登录", command=lambda: accept(False), bg=palette.accent, fg=palette.on_accent, activebackground=palette.accent, activeforeground=palette.on_accent, relief="flat", font=FONT, padx=14, pady=4)
    login_btn.pack(side="left")
    register_btn = tk.Button(bar, text="注册", command=lambda: accept(True), bg=palette.panel, fg=palette.fg, activebackground=palette.card, activeforeground=palette.fg, relief="flat", font=FONT, padx=14, pady=4)
    register_btn.pack(side="left", padx=8)
    win.bind("<Return>", lambda _event: accept(False))
    win.bind("<Escape>", leave)
    win.protocol("WM_DELETE_WINDOW", leave)
    width, height = 460, 440 if legacy_waiting() else 380
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    win.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 2)}")
    win.deiconify()
    win.lift()
    password_box.focus_set()
    win.wait_variable(done)
    try:
        win.withdraw()
    except tk.TclError:
        pass
    if "store" not in result:
        return None
    return result["store"], result["name"]


_SINGLE_HANDLE: list = []


def _single_instance() -> bool:
    """Two windows share one config.json and would overwrite each other's accounts."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel32.CreateMutexW(None, 0, "Local\\LinuxJobDesk")
        if not handle:
            return True
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _SINGLE_HANDLE.append(handle)  # keep it alive for the process lifetime
    except Exception:
        return True
    return True


def main() -> None:
    try:
        if not _single_instance():
            ctypes.windll.user32.MessageBoxW(
                None,
                "作业看台已经开着。\n同时开两个窗口会互相覆盖保存的账号和设置，请先关掉另一个。",
                "作业看台",
                0x40,
            )
            return
        while True:
            _enable_dpi()
            gate = tk.Tk()
            gate.withdraw()
            logged = login_dialog(gate)
            gate.destroy()
            if not logged:
                return
            store, name = logged
            app = App(store=store, user_name=name)
            app.mainloop()
            if not getattr(app, "restart_login", False):
                return
    except Exception as exc:
        _crash(exc)


if __name__ == "__main__":
    main()
