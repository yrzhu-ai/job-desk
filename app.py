"""Desktop window for Slurm jobs on any number of Linux accounts."""

from __future__ import annotations

import ctypes
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import winsound
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from PIL import Image, ImageTk

from ask import AskError, ask_deepseek, completions_url, snapshot_text
from plans import PlanBoard, PlanRemind, center_on, due_plans, tell
from petart import PetArt, find_skin, list_skins
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
from updater import UpdateError, download_release, launch_swap, look_for_update, save_update_url, set_proxy, set_token, update_url
import i18n
from wallpaper import Wallpaper
from fishvideo import FishVideo
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
VERSION = "1.0.20"
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
BG_FITS = (
    ("fill", "填充"),
    ("fit", "适应"),
    ("stretch", "拉伸"),
    ("tile", "平铺"),
    ("center", "居中"),
    ("span", "跨区"),
)
BRIEF = (
    ("run", "运行中"),
    ("wait", "排队"),
    ("done", "已完成"),
    ("bad", "报错"),)


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
    """A small animated pet that also keeps the job counters visible."""

    NUM_W = 96
    NUM_H = 34
    IDLE_TRICK_AFTER = 180.0

    def __init__(self, app: "App") -> None:
        super().__init__(app)
        self.app = app
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#010101")
        try:
            self.wm_attributes("-transparentcolor", "#010101")
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self, width=self.NUM_W, height=self.NUM_H, bg="#010101", highlightthickness=0, cursor="hand2")
        self._num_font = tkfont.Font(self, family="Consolas", size=10, weight="bold")
        self._msg_font = tkfont.Font(self, family="Microsoft YaHei UI", size=9)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.canvas.bind("<Double-Button-1>", self._double)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Enter>", self._enter)
        self.canvas.bind("<Leave>", self._leave)
        self.tip = None
        self.tip_label = None
        self._moved = False
        self._run = 0
        self._wait = 0
        self._done = 0
        self._bad = 0
        self._win_w = self.NUM_W
        self._win_h = self.NUM_H
        self._mode = "num"
        self._message = ""
        self._mode_until = 0.0
        self._pet_state = "idle"
        self._frame = 0
        self._frame_at = 0.0
        self._photo = None
        self._backdrop = None
        self._activity = time.monotonic()
        self._tick_job = None
        self._pending_click = None
        self._gossip_at = time.monotonic() + random.uniform(60, 120)
        self.art = PetArt(self, find_skin(app.store.pet_skin()) or None)
        self.fish = FishVideo()
        self._action = ""
        self._fish_gen = None
        self._fish_at = 0.0
        self._fish_arr = None
        self._fish_bbox = None
        self._fish_layout = None
        self._fish_item = None
        self._count_items: list[int] = []
        self._show_counts = bool(self.app.store.data.get("ball_counts", True))
        self._small_font = tkfont.Font(self, family="Consolas", size=8, weight="bold")
        self._counts_var = tk.BooleanVar(value=self._show_counts)
        self._auto = bool(self.app.store.data.get("fish_auto", True))
        self._auto_var = tk.BooleanVar(value=self._auto)
        self.withdraw()

    def render(self, run: int, wait: int, done: int, bad: int = 0) -> None:
        changed = (run, wait, done, bad) != (self._run, self._wait, self._done, self._bad)
        self._run, self._wait, self._done, self._bad = run, wait, done, bad
        if changed:
            self._activity = time.monotonic()
        if self._mode == "num":
            self._set_size(self._bar_width(), self.NUM_H)
        self._draw()

    def show(self, run: int, wait: int, done: int, bad: int = 0) -> None:
        self._run, self._wait, self._done, self._bad = run, wait, done, bad
        self._activity = time.monotonic()
        if self.fish.ready and self.app.store.ball_style() == "fish":
            self._start_fish(self.fish.pick_idle())
        else:
            self._mode = "num"
            self._set_size(self._bar_width(), self.NUM_H)
        pos = self.app.store.data.get("ball_pos") or []
        if isinstance(pos, list) and len(pos) == 2:
            try:
                x, y = int(pos[0]), int(pos[1])
            except (TypeError, ValueError):
                x, y = self._default_pos()
        else:
            x, y = self._default_pos()
        width, height = self._win_w, self._win_h
        x = max(0, min(x, self.winfo_screenwidth() - width))
        y = max(0, min(y, self.winfo_screenheight() - height - 56))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self._draw()
        self._start_tick()

    def hide(self) -> None:
        self._hide_tip()
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except tk.TclError:
                pass
            self._tick_job = None
        self.withdraw()

    def _set_size(self, width: int, height: int) -> None:
        if (width, height) == (self._win_w, self._win_h):
            return
        self._win_w, self._win_h = width, height
        try:
            self.canvas.configure(width=width, height=height)
            if self.winfo_viewable():
                self.geometry(f"{width}x{height}+{self.winfo_x()}+{self.winfo_y()}")
        except tk.TclError:
            pass

    # ---------- reactions ----------
    def celebrate(self, kind: str, count: int) -> None:
        """Job finished: show the pet when art exists, otherwise a short message."""
        try:
            if not self.winfo_viewable():
                return
        except tk.TclError:
            return
        if kind == "done":
            text = i18n.tr(f"完成 {count} 个任务！") if count > 1 else i18n.tr("搞定一个！")
            state = "happy"
        else:
            text = i18n.tr("别灰心，下次一定行！")
            state = "sad"
        self._activity = time.monotonic()
        if self.art.ready and state in self.art.frames:
            self._enter_pet(state)
        else:
            self._enter_text(text, 3000)

    def _enter_text(self, text: str, hold_ms: int) -> None:
        self._message = text
        self._mode = "text"
        self._mode_until = time.monotonic() + hold_ms / 1000
        self._set_size(self._bar_width(), self.NUM_H)
        self._draw()

    def _enter_pet(self, state: str) -> None:
        self._pet_state = state if state in self.art.frames else "idle"
        self._frame = 0
        self._frame_at = time.monotonic()
        self._mode = "pet"
        hold = self.art.hold(self._pet_state) or 3000
        self._mode_until = time.monotonic() + hold / 1000
        width = max(self.NUM_W, self.art.width)
        height = max(self.NUM_H, self.art.height)
        self._set_size(width, height)
        self._draw()

    def _fish_size(self) -> tuple[int, int]:
        width = int(self.app.store.fish_width())
        return width, max(1, int(width * 1.3))

    def _pick_next(self) -> str:
        if self._auto:
            pick = self.fish.pick_random() if random.random() < 0.4 else self.fish.pick_idle()
        else:
            pick = self._action or self.fish.pick_idle()
        if pick == self._action and len(self.fish.actions) > 1:
            pick = self.fish.pick_random()
        return pick

    def _start_fish(self, action: str) -> None:
        if not self.fish.exists(action):
            action = self.fish.pick_idle()
        self._action = action
        self._fish_bbox = self.fish.clip_bbox(action)
        self._fish_gen = self.fish.frames(action)
        self._fish_at = 0.0
        self._mode = "fish"
        fish_w, fish_h = self._fish_size()
        width = max(fish_w + 12, self.NUM_W)
        height = fish_h + (24 if self._show_counts else 6)
        self._set_size(width, height)
        self._advance_fish()

    def _advance_fish(self) -> None:
        arr = None
        if self._fish_gen is not None:
            try:
                arr = next(self._fish_gen)
            except StopIteration:
                arr = None
            except Exception:
                arr = None
        if arr is None:
            self._start_fish(self._pick_next())
            return
        self._fish_arr = arr
        self._draw_fish()

    def _draw_fish(self) -> None:
        if self._fish_arr is None:
            return
        canvas = self.canvas
        width, height = self._win_w, self._win_h
        fish_w, fish_h = self._fish_size()
        image = Image.fromarray(self._fish_arr, "RGBA")
        if self._fish_bbox:
            image = image.crop(self._fish_bbox)
        scale = min(fish_w / max(image.width, 1), fish_h / max(image.height, 1))
        size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(size, Image.LANCZOS)
        mask = image.getchannel("A").point(lambda value: 255 if value >= 72 else 0)
        backdrop = Image.new("RGBA", (fish_w, fish_h), (1, 1, 1, 255))
        backdrop.paste(image, ((fish_w - size[0]) // 2, (fish_h - size[1]) // 2), mask)
        self._photo = ImageTk.PhotoImage(backdrop, master=self)
        canvas.delete("all")
        canvas.create_image(width / 2, fish_h / 2 + 2, image=self._photo)
        self._fish_item = None
        if not self._show_counts:
            return
        top = fish_h + 2
        canvas.create_rectangle(1, top, width - 1, height - 1, fill=palette.card, outline=palette.line)
        segments = [
            (str(self._run), palette.ok),
            ("/", palette.muted),
            (str(self._wait), palette.warn),
            ("/", palette.muted),
            (str(self._done), palette.fg),
            ("/", palette.muted),
            (str(self._bad), palette.bad),
        ]
        total = sum(self._small_font.measure(text) for text, _color in segments)
        x = (width - total) / 2
        for text, color in segments:
            canvas.create_text(x, (top + height) / 2, text=text, fill=color, font=self._small_font, anchor="w")
            x += self._small_font.measure(text)

    def toggle_counts(self) -> None:
        self._show_counts = bool(self._counts_var.get())
        self.app.store.data["ball_counts"] = self._show_counts
        self.app.store.save()
        if self._mode == "fish":
            self._start_fish(self._action or self.fish.pick_idle())
        else:
            self._draw()

    def open_actions(self) -> None:
        ActionListWindow(self.app, self)

    def _back_to_numbers(self) -> None:
        self._mode = "num"
        self._mode_until = 0.0
        self._activity = time.monotonic()
        self._set_size(self.NUM_W, self.NUM_H)
        self._draw()

    # ---------- drawing ----------
    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        canvas = self.canvas
        canvas.delete("all")
        if self._mode == "fish" and self.fish.ready:
            self._draw_fish()
        elif self._mode == "pet" and self.art.ready:
            self._draw_pet()
        else:
            self._draw_numbers()

    def _segments(self) -> list[tuple[str, str]]:
        return [
            (str(self._run), palette.ok),
            (" / ", palette.muted),
            (str(self._wait), palette.warn),
            (" / ", palette.muted),
            (str(self._done), palette.fg),
            (" / ", palette.muted),
            (str(self._bad), palette.bad),
        ]

    def _bar_width(self) -> int:
        if self._mode == "text" and self._message:
            return max(self.NUM_W, self._msg_font.measure(self._message) + 28)
        total = sum(self._num_font.measure(text) for text, _color in self._segments())
        # keep a stable minimum width so the bar does not jitter as digits change
        steady = self._num_font.measure("00 / 00 / 000 / 00") + 22
        return max(self.NUM_W, total + 28, steady)

    def _draw_numbers(self) -> None:
        canvas = self.canvas
        width, height = self._win_w, self._win_h
        text_mode = self._mode == "text"
        base = palette.accent if text_mode else palette.card
        photo = None
        wallpaper = getattr(self.app, "wallpaper", None)
        if wallpaper is not None and wallpaper.ready:
            photo = wallpaper.tile(self, width, height, base, 0.55 if text_mode else 0.30)
        if photo is not None:
            self._backdrop = photo
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.create_rectangle(1, 1, width - 1, height - 1, outline=palette.line)
        else:
            canvas.create_rectangle(1, 1, width - 1, height - 1, fill=base, outline=palette.line)
        if text_mode:
            canvas.create_text(width / 2, height / 2, text=self._message, fill=palette.on_accent, font=self._msg_font)
            return
        segments = self._segments()
        total = sum(self._num_font.measure(text) for text, _color in segments)
        x = (width - total) / 2
        for text, color in segments:
            canvas.create_text(x, height / 2, text=text, fill=color, font=self._num_font, anchor="w")
            x += self._num_font.measure(text)

    def _draw_pet(self) -> None:
        images = self.art.images(self._pet_state)
        if not images:
            self._back_to_numbers()
            return
        image = images[self._frame % len(images)]
        self._photo = image
        self.canvas.create_image(self._win_w / 2, self._win_h / 2, image=image)

    # ---------- animation ----------
    def _start_tick(self) -> None:
        if self._tick_job is None:
            self._tick_job = self.after(1, self._tick)

    def _tick(self) -> None:
        self._tick_job = None
        if not self.winfo_exists() or not self.winfo_viewable():
            return
        now = time.monotonic()
        interval = 90
        if self._mode == "fish":
            step = 1.0 / max(self.fish.fps, 1)
            interval = max(16, int(step * 1000))
            if now - self._fish_at >= step:
                behind = min(int((now - self._fish_at) / step), 3)
                for _ in range(max(1, behind)):
                    try:
                        self._advance_fish()
                    except Exception:
                        break
                self._fish_at = now
        elif self._mode != "num" and self._mode_until and now >= self._mode_until:
            self._back_to_numbers()
        elif self._mode == "pet" and self.art.ready:
            step = self.art.ms(self._pet_state) / 1000
            if now - self._frame_at >= step:
                self._frame_at = now
                self._frame += 1
                self._draw()
        elif self._mode == "num" and self.art.ready and now - self._activity >= self.IDLE_TRICK_AFTER:
            if "trick" in self.art.frames:
                self._enter_pet("trick")
            else:
                self._activity = now
        elif self._mode == "num" and now >= self._gossip_at:
            self._gossip_at = now + random.uniform(480, 900)
            if 8 <= datetime.now().hour < 23:
                text = self.app.ball_gossip()
                if text:
                    self._enter_text(text, 4200)
        try:
            self._draw()
        except Exception:
            pass
        self._tick_job = self.after(interval, self._tick)
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
            x = self.winfo_x() + self._win_w + 12
        y = max(8, self.winfo_y())
        self.tip.geometry(f"+{x}+{y}")
        self.tip.deiconify()

    def _hide_tip(self) -> None:
        if self.tip is not None:
            self.tip.withdraw()

    def _default_pos(self) -> tuple[int, int]:
        return self.winfo_screenwidth() - self.NUM_W - 28, self.winfo_screenheight() - self.NUM_H - 110

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
        if self._pending_click is not None:
            return
        self._pending_click = self.after(240, self._interact)

    def _interact(self) -> None:
        self._pending_click = None
        self._reaction()

    def _reaction(self) -> None:
        if not self.fish.ready:
            self.pat()
            return
        candidates = [name for name in self.fish.names() if "开心" in name or "点击" in name]
        action = random.choice(candidates) if candidates else self.fish.pick_random()
        was_auto = self._auto
        self._auto = False
        self._start_fish(action)
        if was_auto:
            self.after(6000, self._resume_auto)

    def _resume_auto(self) -> None:
        self._auto = True
        self._auto_var.set(True)

    def _toggle_auto(self) -> None:
        self._auto = bool(self._auto_var.get())
        self.app.store.data["fish_auto"] = self._auto
        self.app.store.save()

    def _open_window(self) -> None:
        self._pending_click = None
        self.app.restore_from_ball()

    def _double(self, _event) -> None:
        if self._pending_click is not None:
            try:
                self.after_cancel(self._pending_click)
            except tk.TclError:
                pass
            self._pending_click = None
        self._open_window()

    def pat(self) -> None:
        """A pat on the head: happy animation, or a short message without art."""
        if self.art.ready:
            self._enter_pet("happy")
        else:
            self._enter_text(i18n.tr("嘿嘿~"), 2000)

    def reload_art(self) -> None:
        self.art = PetArt(self, find_skin(self.app.store.pet_skin()) or None)
        self._back_to_numbers()

    def _menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="打开", command=self._open_window)
        if self.fish.ready:
            menu.add_command(label="互动", command=self._reaction)
            menu.add_checkbutton(label="随机动作", variable=self._auto_var, command=self._toggle_auto)
            menu.add_command(label="动作列表…", command=self.open_actions)
            menu.add_checkbutton(label="显示数字", variable=self._counts_var, command=self.toggle_counts)
        else:
            menu.add_command(label="摸摸头", command=self.pat)
            skins = list_skins()
            if skins:
                sub = tk.Menu(menu, tearoff=0)
                for name in skins:
                    sub.add_command(label=name, command=lambda skin=name: self.app.set_pet_skin(skin))
                sub.add_separator()
                sub.add_command(label="不用宠物", command=lambda: self.app.set_pet_skin(""))
                menu.add_cascade(label="换个形象", menu=sub)
        menu.add_command(label="立即刷新", command=self._refresh)
        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        i18n.apply(menu)
        menu.tk_popup(event.x_root, event.y_root)

    def _refresh(self) -> None:
        self.app.restore_from_ball()
        self.app.refresh()

    def _quit(self) -> None:
        if messagebox.askyesno("退出", "要退出作业看台吗？", parent=self):
            self.app.on_close()


class ActionListWindow(tk.Toplevel):
    """Pick one of the fish animations to play on the ball."""

    def __init__(self, app: "App", ball: FloatBall) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.ball = ball
        self.title("动作列表")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.minsize(360, 420)
        pad = tk.Frame(self, bg=BG)
        pad.pack(fill="both", expand=True, padx=14, pady=12)
        self.filter_var = tk.StringVar()
        entry = tk.Entry(pad, textvariable=self.filter_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.pack(fill="x", ipady=4)
        box = tk.Frame(pad, bg=BG)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.listbox = tk.Listbox(box, bg=PANEL, fg=FG, selectbackground=ACCENT, selectforeground=palette.on_accent, relief="flat", font=FONT_SMALL, activestyle="none", exportselection=False)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.buttons = tk.Frame(pad, bg=BG)
        self.buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(self.buttons, text="播放", style="Accent.TButton", command=self.play_selected).pack(side="left")
        ttk.Button(self.buttons, text="随机", style="Ghost.TButton", command=self.play_random).pack(side="left", padx=6)
        ttk.Button(self.buttons, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        self.filter_var.trace_add("write", lambda *_args: self.refill())
        self.listbox.bind("<Double-Button-1>", lambda _event: self.play_selected())
        self.refill()
        width, height = 420, 500
        try:
            x = max(0, ball.winfo_x() + ball._win_w - width)
            y = max(0, ball.winfo_y() - height - 8)
        except tk.TclError:
            x, y = 200, 200
        if y < 8:
            y = max(8, ball.winfo_y() + ball._win_h + 8)
        x = max(8, min(x, self.winfo_screenwidth() - width - 8))
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()
        entry.focus_set()

    def refill(self) -> None:
        keyword = self.filter_var.get().strip().lower()
        self.listbox.delete(0, "end")
        self._shown = [name for name in self.ball.fish.names() if not keyword or keyword in name.lower()]
        for name in self._shown:
            self.listbox.insert("end", name)

    def play_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self._shown[selection[0]]
        if not self.ball.winfo_viewable():
            self.app.minimize_to_ball()
        self.ball._auto = False
        self.ball._auto_var.set(False)
        self.ball._start_fish(name)

    def play_random(self) -> None:
        if not self.ball.winfo_viewable():
            self.app.minimize_to_ball()
        self.ball._auto = True
        self.ball._auto_var.set(True)
        self.ball._start_fish(self.ball.fish.pick_random())


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
        self.title("设置")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        self.base_var = tk.StringVar(value=app.store.api_base())
        self.model_var = tk.StringVar(value=app.store.api_model())
        self.key_var = tk.StringVar()
        self.show_var = tk.BooleanVar(value=False)
        self.token_var = tk.StringVar()
        self.proxy_var = tk.StringVar(value=app.store.proxy())
        self.bg_var = tk.StringVar(value=app.store.bg_image())
        self.fit_var = tk.StringVar(value=i18n.tr(dict(BG_FITS).get(app.store.bg_fit(), "填充")))
        self._fit_by_label = {i18n.tr(label): key for key, label in BG_FITS}
        self.skin_var = tk.StringVar(value=i18n.tr(SKINS[palette.name]["label"]))
        self.size_var = tk.StringVar(value=str(app.store.text_size()))
        self.lang_var = tk.StringVar(value=i18n.tr(dict(i18n.LANGUAGES).get(app.store.language(), "跟随系统")))
        self._skin_by_label = {i18n.tr(spec["label"]): key for key, spec in SKINS.items()}
        self._lang_by_label = {i18n.tr(label): key for key, label in i18n.LANGUAGES}
        self.note = tk.StringVar(value="密钥留空表示不修改。" if app.store.has_api_key() else "还没有密钥。")
        self.token_note = tk.StringVar(value="已经填过 Token（留空表示不修改）。" if app.store.has_github_token() else "还没有填 Token（可选）。")

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=14, pady=(14, 6))
        self._tab_look(tabs)
        self._tab_account(tabs)
        self._tab_advanced(tabs)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        ttk.Button(bar, text="确定", style="Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self.destroy).pack(side="right")
        center_on(self, app, 700, 600)
        self.deiconify()
        self.grab_set()

    def _page(self, tabs: ttk.Notebook, title: str) -> tk.Frame:
        page = tk.Frame(tabs, bg=BG, padx=14, pady=12)
        tabs.add(page, text=title)
        page.columnconfigure(1, weight=1)
        return page

    def _caption(self, page: tk.Frame, row: int, text: str) -> None:
        tk.Label(page, text=text, bg=BG, fg=FG, font=FONT, width=10, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=5)

    def _hint(self, page: tk.Frame, row: int, text: str) -> None:
        tk.Label(page, text=text, bg=BG, fg=MUTED, font=FONT_SMALL, wraplength=460, justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 6))

    def _tab_look(self, tabs: ttk.Notebook) -> None:
        page = self._page(tabs, "外观")
        self._caption(page, 0, "皮肤")
        skin = ttk.Combobox(page, state="readonly", textvariable=self.skin_var, values=list(self._skin_by_label))
        skin.grid(row=0, column=1, sticky="ew", pady=5)
        skin.bind("<<ComboboxSelected>>", self._on_skin)
        self._caption(page, 1, "文字大小")
        size = ttk.Combobox(page, state="readonly", textvariable=self.size_var, values=[str(value) for value in TEXT_SIZES])
        size.grid(row=1, column=1, sticky="ew", pady=5)
        size.bind("<<ComboboxSelected>>", self._on_size)
        self._caption(page, 2, "语言")
        lang = ttk.Combobox(page, state="readonly", textvariable=self.lang_var, values=list(self._lang_by_label))
        lang.grid(row=2, column=1, sticky="ew", pady=5)
        lang.bind("<<ComboboxSelected>>", self._on_lang)
        self._caption(page, 3, "背景图片")
        bgrow = tk.Frame(page, bg=BG)
        bgrow.grid(row=3, column=1, sticky="ew", pady=5)
        entry = tk.Entry(bgrow, textvariable=self.bg_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT_SMALL, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(bgrow, text="浏览…", style="Ghost.TButton", command=self.pick_bg).pack(side="left", padx=(6, 0))
        ttk.Button(bgrow, text="清除", style="Ghost.TButton", command=self.clear_bg).pack(side="left", padx=(6, 0))
        self._hint(page, 4, "可选。选一张图片铺在便利贴看板和悬浮条上；图片会按当前皮肤色调淡化，保证文字清楚。")
        self._caption(page, 5, "契合度")
        fit = ttk.Combobox(page, state="readonly", textvariable=self.fit_var, values=[i18n.tr(label) for _key, label in BG_FITS])
        fit.grid(row=5, column=1, sticky="ew", pady=5)
        self._hint(page, 6, "和 Windows 壁纸一样：填充铺满、适应完整显示、拉伸变形铺满、平铺重复、居中居中放置、跨区整块拉伸。")
        self._caption(page, 7, "悬浮球")
        self.ball_style_var = tk.StringVar(value="鱼" if self.app.store.ball_style() == "fish" else "只显示数字")
        ball_style = ttk.Combobox(page, state="readonly", textvariable=self.ball_style_var, values=["鱼", "只显示数字"])
        ball_style.grid(row=7, column=1, sticky="ew", pady=5)
        ball_style.bind("<<ComboboxSelected>>", self._on_ball_style)
        self._caption(page, 8, "鱼的大小")
        self.fish_size_var = tk.StringVar(value=str(self.app.store.fish_width()))
        fish_size = ttk.Combobox(page, state="readonly", textvariable=self.fish_size_var, values=["96", "120", "160"])
        fish_size.grid(row=8, column=1, sticky="ew", pady=5)
        fish_size.bind("<<ComboboxSelected>>", self._on_fish_size)

    def _tab_advanced(self, tabs: ttk.Notebook) -> None:
        page = self._page(tabs, "高级")
        tk.Label(page, text="这些选项一般不用改，出问题时再动。", bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(page, text="检查更新", style="Accent.TButton", command=self._check_updates).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._row(page, 2, "接口地址", self.base_var)
        self._row(page, 3, "模型", self.model_var)
        self.key_entry = self._row(page, 4, "API Key", self.key_var, show="*")
        tk.Checkbutton(page, text="显示密钥", variable=self.show_var, command=self.toggle, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).grid(row=5, column=1, sticky="w")
        tk.Label(page, textvariable=self.note, bg=BG, fg=WARN, font=FONT_SMALL, wraplength=420, justify="left").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(page, text="清除密钥", style="Ghost.TButton", command=self.clear_key).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _tab_net(self, tabs: ttk.Notebook) -> None:
        page = self._page(tabs, "网络与更新")
        self._caption(page, 0, "GitHub Token")
        entry = tk.Entry(page, textvariable=self.token_var, show="*", bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.grid(row=0, column=1, sticky="ew", pady=5, ipady=4)
        self._hint(page, 1, "可选。填一个 GitHub Token，更新检查的额度会从每小时 60 次提升到 5000 次。在 GitHub → Settings → Developer settings 生成，权限只需 public_repo（或只读）。留空表示不修改。")
        tk.Label(page, textvariable=self.token_note, bg=BG, fg=MUTED, font=FONT_SMALL, wraplength=460, justify="left").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._caption(page, 3, "代理")
        proxy = tk.Entry(page, textvariable=self.proxy_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        proxy.grid(row=3, column=1, sticky="ew", pady=5, ipady=4)
        self._hint(page, 4, "可选。例如 http://127.0.0.1:7897。Windows 系统代理开着时优先用系统的；没开又需要下载更新时，可以在这里填。")
        ttk.Button(page, text="检查更新", style="Ghost.TButton", command=lambda: self.app.check_updates()).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _tab_deepseek(self, tabs: ttk.Notebook) -> None:
        page = self._page(tabs, "DeepSeek")
        self._row(page, 0, "接口地址", self.base_var)
        self._row(page, 1, "模型", self.model_var)
        self.key_entry = self._row(page, 2, "API Key", self.key_var, show="*")
        tk.Checkbutton(page, text="显示密钥", variable=self.show_var, command=self.toggle, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG, font=FONT_SMALL).grid(row=3, column=1, sticky="w")
        self._hint(page, 4, "使用快速回答，不开启深度思考。只发送作业状态或你写下的那段话，不发送账号密码。")
        tk.Label(page, textvariable=self.note, bg=BG, fg=WARN, font=FONT_SMALL, wraplength=420, justify="left").grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Button(page, text="清除密钥", style="Ghost.TButton", command=self.clear_key).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _tab_account(self, tabs: ttk.Notebook) -> None:
        page = self._page(tabs, "账号")
        self._caption(page, 0, "当前用户")
        tk.Label(page, text=self.app.user_name, bg=BG, fg=FG, font=FONT, anchor="w").grid(row=0, column=1, sticky="w", pady=5)
        self._hint(page, 1, "退出登录后可以用另一个 Windows 用户重新登记，账号和便利贴各自独立保存。")
        ttk.Button(page, text="退出登录", style="Ghost.TButton", command=self._logout).grid(row=2, column=0, columnspan=2, sticky="w")

    def _on_skin(self, _event=None) -> None:
        key = self._skin_by_label.get(self.skin_var.get())
        if key:
            self.app.apply_skin(key)

    def _on_size(self, _event=None) -> None:
        try:
            size = int(self.size_var.get())
        except ValueError:
            return
        self.app.apply_text_style(self.app.store.text_family(), size)

    def _check_updates(self) -> None:
        self.destroy()
        self.app.after(30, self.app.check_updates)

    def _on_ball_style(self, _event=None) -> None:
        style = "fish" if self.ball_style_var.get() == "鱼" else "bar"
        self.app.store.set_ball_style(style)
        self.app.apply_ball_style()

    def _on_fish_size(self, _event=None) -> None:
        try:
            width = int(self.fish_size_var.get())
        except ValueError:
            return
        self.app.store.set_fish_width(width)
        self.app.apply_ball_style()

    def _on_lang(self, _event=None) -> None:
        key = self._lang_by_label.get(self.lang_var.get())
        if key:
            self.app.apply_language(key)
            self.title(i18n.tr("设置"))

    def _logout(self) -> None:
        if messagebox.askyesno("退出登录", "要退出当前用户吗？", parent=self):
            self.destroy()
            self.app.logout()

    def _row(self, parent, row: int, caption: str, variable: tk.StringVar, show: str = "") -> tk.Entry:
        tk.Label(parent, text=caption, bg=BG, fg=FG, font=FONT, width=10, anchor="e").grid(row=row, column=0, sticky="e", padx=(0, 8), pady=5)
        entry = tk.Entry(parent, textvariable=variable, show=show, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        entry.grid(row=row, column=1, sticky="ew", pady=5, ipady=4)
        return entry

    def pick_bg(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择背景图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("所有文件", "*.*")],
        )
        if path:
            self.bg_var.set(path)

    def clear_bg(self) -> None:
        self.bg_var.set("")

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
        token = self.token_var.get().replace("\r", "").replace("\n", "").strip()
        if token:
            try:
                self.app.store.set_github_token(token)
            except SecretError as exc:
                messagebox.showerror("DeepSeek", str(exc), parent=self)
                return
            set_token(token)
            self.token_var.set("")
            self.token_note.set("已经填过 Token（留空表示不修改）。")
        proxy = self.proxy_var.get().strip()
        self.app.store.set_proxy(proxy)
        set_proxy(proxy)
        fit = self._fit_by_label.get(self.fit_var.get(), "fill")
        self.app.set_bg_image(self.bg_var.get().strip(), fit)
        self.key_var.set("")
        self.note.set("已保存。")
        self.destroy()

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


def _plain_notes(text: str) -> str:
    """Turn GitHub release markdown into something readable in a plain Text box."""
    value = str(text or "")
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"^\s*#+\s*", "", value, flags=re.MULTILINE)
    lines = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        if "Full Changelog" in line or "/compare/" in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


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
        notes = _plain_notes(offer.notes) or "这一版主要是细节修复，直接点「现在更新」即可。"
        self.notes.insert("1.0", notes[:4000])
        self.notes.configure(state="disabled")
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(bar, text="现在更新", style="Accent.TButton", command=self.install).pack(side="left")
        ttk.Button(bar, text="稍后", style="Ghost.TButton", command=self.destroy).pack(side="left", padx=8)
        ttk.Button(bar, text="跳过这个版本", style="Ghost.TButton", command=self.skip).pack(side="right")
        center_on(self, app, 560, 420)
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
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


class WrapBar(tk.Frame):
    """Buttons flow left to right and wrap onto new lines when the window narrows."""

    def __init__(self, master, gap: int = 6, row_height: int = 34) -> None:
        super().__init__(master, bg=BG)
        self.gap = gap
        self.row_height = row_height
        self.items: list[tk.Widget] = []
        self._last_width = -1
        self.bind("<Configure>", self._on_configure)

    def add(self, widget: tk.Widget) -> tk.Widget:
        self.items.append(widget)
        widget.place(x=0, y=0)
        self._reflow()
        return widget

    def _on_configure(self, event) -> None:
        if abs(event.width - self._last_width) > 2:
            self._last_width = event.width
            self._reflow(event.width)

    def _reflow(self, width: int | None = None) -> None:
        available = width if width else self.winfo_width()
        if available <= 1:
            return
        x = 0
        row = 0
        for widget in self.items:
            try:
                widget.update_idletasks()
                need = widget.winfo_reqwidth() + self.gap
            except tk.TclError:
                continue
            if x and x + need > available:
                row += 1
                x = 0
            widget.place(x=x, y=row * self.row_height)
            x += need
        try:
            self.configure(height=(row + 1) * self.row_height)
        except tk.TclError:
            pass


class App(tk.Tk):
    def __init__(self, store: Store | None = None, user_name: str = "") -> None:
        _enable_dpi()
        super().__init__()
        self.store = store or Store()
        set_token(self.store.github_token())
        set_proxy(self.store.proxy())
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
        self.wallpaper = Wallpaper()
        if not self.wallpaper.load(self.store.bg_image(), self.store.bg_fit()):
            self.store.set_bg_image("")
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
            menu.add_command(label=i18n.tr(label), command=lambda name=key: self.apply_language(name))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def apply_language(self, choice: str) -> None:
        self.store.set_language(choice)
        i18n.language.code = i18n.resolve(choice)
        i18n.apply(self)
        self.title(self._window_title())
        if hasattr(self, "plan_board"):
            self.plan_board.apply_language()
        self.redraw()

    def open_skin_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for key, spec in SKINS.items():
            label = i18n.tr(spec["label"])
            if key == palette.name:
                label += "    " + i18n.tr("当前")
            menu.add_command(label=label, command=lambda name=key: self.apply_skin(name))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def apply_ball_style(self) -> None:
        if not hasattr(self, "ball") or not self.ball.winfo_exists():
            return
        if not self.ball.winfo_viewable():
            return
        if self.store.ball_style() == "fish" and self.ball.fish.ready:
            self.ball._start_fish(self.ball._action or self.ball.fish.pick_idle())
        else:
            self.ball._back_to_numbers()

    def set_bg_image(self, path: str, mode: str | None = None) -> None:
        fit = mode or self.store.bg_fit()
        ok = self.wallpaper.load(path, fit)
        self.store.set_bg_image(self.wallpaper.path if ok else "")
        self.store.set_bg_fit(fit)
        if hasattr(self, "ball") and self.ball.winfo_exists():
            self.ball.render(*self.ball_numbers())
        if hasattr(self, "plan_board"):
            self.plan_board._paint_backdrop()

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
        if hasattr(self, "ball") and self.ball.winfo_exists():
            self.ball.render(*self.ball_numbers())
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
        nav = WrapBar(header)
        nav.pack(fill="x")
        self.jobs_mode_btn = ttk.Button(nav, text="作业", command=lambda: self.set_mode("jobs"))
        nav.add(self.jobs_mode_btn)
        self.plans_mode_btn = ttk.Button(nav, text="管家", command=lambda: self.set_mode("plans"))
        nav.add(self.plans_mode_btn)
        nav.add(ttk.Button(nav, text="账号密码", style="Accent.TButton", command=self.open_accounts))
        self.brief_btn = ttk.Button(nav, text="简洁", command=lambda: self.set_view("brief"))
        nav.add(self.brief_btn)
        self.full_btn = ttk.Button(nav, text="完整", command=lambda: self.set_view("full"))
        nav.add(self.full_btn)
        self.refresh_btn = ttk.Button(nav, text="立即刷新", style="Accent.TButton", command=self.refresh)
        nav.add(self.refresh_btn)
        nav.add(ttk.Button(nav, text="悬浮球", style="Ghost.TButton", command=self.minimize_to_ball))
        self.hide_done = tk.BooleanVar(value=bool(self.store.data.get("hide_done_jobs")))
        self.hide_bad = tk.BooleanVar(value=bool(self.store.data.get("hide_bad_jobs")))
        self.update_btn = ttk.Button(nav, text="检查更新", style="Ghost.TButton", command=self.check_updates)
        nav.add(ttk.Button(nav, text="设置", style="Ghost.TButton", command=self.open_settings))

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
        row1 = ttk.Frame(tool, style="App.TFrame")
        row1.pack(fill="x")
        row2 = ttk.Frame(tool, style="App.TFrame")
        row2.pack(fill="x", pady=(6, 0))

        self.filter_bar = ttk.Frame(row1, style="App.TFrame")
        self.filter_bar.pack(side="left")
        self.filter_buttons: dict[str, ttk.Button] = {}
        for key, title in FILTERS:
            button = ttk.Button(self.filter_bar, text=title, style="Ghost.TButton", command=lambda name=key: self.set_filter(name))
            button.pack(side="left", padx=(0, 6))
            self.filter_buttons[key] = button
        self.top_on = False
        self.top_btn = ttk.Button(self.filter_bar, text="top", style="Ghost.TButton", command=self.toggle_top)
        self.top_btn.pack(side="left", padx=(0, 6))
        self.later_btn = ttk.Button(row1, text="稍后", style="Ghost.TButton", command=self.open_later)

        self.search_caption = ttk.Label(row2, text="搜索", style="Muted.TLabel")
        self.search_caption.pack(side="left", padx=(0, 4))
        search = tk.Entry(row2, textvariable=self.search_var, width=18, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        search.pack(side="left", ipady=3)
        self.search_var.trace_add("write", lambda *_args: self.redraw())
        ttk.Label(row2, text="结束作业近", style="Muted.TLabel").pack(side="left", padx=(12, 4))
        self.days_box = ttk.Combobox(row2, width=4, state="readonly", values=("1", "3", "7", "14", "30"))
        self.days_box.set(str(self.store.history_days()))
        self.days_box.pack(side="left")
        self.days_box.bind("<<ComboboxSelected>>", self.on_days)
        ttk.Label(row2, text="天", style="Muted.TLabel").pack(side="left", padx=(4, 0))
        meta = ttk.Frame(row2, style="App.TFrame")
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
        self.plans_mode_btn.configure(text=f"{i18n.tr('管家')} {due}" if due else i18n.tr("管家"), style="Accent.TButton" if self.mode == "plans" else "Ghost.TButton")

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
            self.later_btn.configure(text=f"{i18n.tr('稍后')} {count}")
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
                if self.later_btn.winfo_ismapped():
                    self.filter_bar.pack(side="left", before=self.later_btn)
                else:
                    self.filter_bar.pack(side="left")

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
            if time.monotonic() - getattr(self, "_update_started", 0.0) < 20:
                return
            self._updating = False
        self._update_started = time.monotonic()
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
        try:
            if hasattr(self, "update_btn"):
                self.update_btn.configure(text="检查中…")
        except tk.TclError:
            pass

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
        page = "https://github.com/yrzhu-ai/job-desk/releases/latest"
        try:
            if hasattr(self, "update_btn"):
                self.update_btn.configure(text=i18n.tr("检查更新"))
        except tk.TclError:
            pass
        if error:
            if not silent:
                if messagebox.askyesno("检查更新", f"{error}\n\n要打开下载页面自己下载吗？\n{page}", parent=self):
                    import webbrowser

                    webbrowser.open(page)
            return
        if found is None:
            try:
                self.update_btn.configure(text=i18n.tr("检查更新"))
            except tk.TclError:
                pass
            if not silent:
                messagebox.showinfo("检查更新", f"已经是最新版本 {VERSION}。", parent=self)
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
        win = tk.Toplevel(self)
        win.title("正在下载")
        win.configure(bg=BG)
        win.transient(self)
        win.resizable(False, False)
        tk.Label(win, text=f"正在下载 {found.version}…", bg=BG, fg=FG, font=FONT).pack(padx=24, pady=(18, 8))
        bar = ttk.Progressbar(win, mode="determinate", length=300, maximum=100, value=0)
        bar.pack(padx=24, pady=(0, 6))
        status = tk.Label(win, text="正在连接…", bg=BG, fg=MUTED, font=FONT_SMALL)
        status.pack(padx=24, pady=(0, 14))

        def on_progress(done: int, total: int) -> None:
            def update() -> None:
                if not win.winfo_exists():
                    return
                if total > 0:
                    percent = min(100.0, done * 100.0 / total)
                    bar.configure(value=percent)
                    status.configure(text=f"{percent:.0f}%    {done / 1048576:.1f} / {total / 1048576:.1f} MB")
                else:
                    status.configure(text=f"{done / 1048576:.1f} MB")

            self.after(0, update)

        try:
            center_on(win, self, 380, 160)
        except Exception:
            win.geometry("380x160")
        win.deiconify()
        win.lift()
        win.focus_force()

        def close() -> None:
            try:
                win.grab_release()
                win.destroy()
            except tk.TclError:
                pass

        def work() -> None:
            path = None
            problem = ""
            try:
                path = download_release(found.url, found.sha256, found.size, progress=on_progress)
            except UpdateError as exc:
                problem = str(exc)
            except Exception as exc:
                problem = f"下载没有完成：{exc}"
            self.after(0, close)
            self.after(50, lambda item=path, text=problem: self._finish_download(item, text))

        threading.Thread(target=work, daemon=True).start()

    def _finish_download(self, path, problem: str) -> None:
        self._updating = False
        if not self.winfo_exists():
            return
        if problem or path is None:
            tell(self, "更新", problem or "下载没有完成。")
            return
        if self._swap_inplace(path):
            self.on_close()
            return
        tell(self, "更新", f"新版本已下载到：\n{path}\n\n但当前目录不可写，请手动复制替换。")

    def _swap_inplace(self, downloaded) -> bool:
        """Rename this exe aside, copy the new one into its place, start it."""
        target = Path(sys.executable)
        old = target.with_name(target.stem + ".old.exe")
        try:
            if old.exists():
                old.unlink()
            target.rename(old)
            shutil.copy2(downloaded, target)
        except OSError:
            try:
                if not target.exists() and old.exists():
                    old.rename(target)
            except OSError:
                pass
            return False
        try:
            downloaded.unlink()
        except OSError:
            pass
        try:
            subprocess.Popen([str(target)], close_fds=True)
        except OSError:
            return False
        return True

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
        run, wait, done, bad = self.ball_numbers()
        self.withdraw()
        self.ball.show(run, wait, done, bad)
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

    def ball_numbers(self) -> tuple[int, int, int, int]:
        run, wait, done, bad = self._counts_for(None)
        return run, wait, done, bad

    def ball_gossip(self) -> str:
        """A short proactive line for the pet, based on what is happening."""
        run, wait, done, bad = self.ball_numbers()
        hour = datetime.now().hour
        options: list[str] = []
        if run:
            options.append(i18n.tr(f"还有 {run} 个在跑～"))
        if wait:
            options.append(i18n.tr(f"{wait} 个在排队，别急～"))
        if not run and not wait:
            options.append(i18n.tr("都跑完啦，休息一下～"))
        if hour < 11:
            options.append(i18n.tr("早上好！"))
        elif hour >= 22:
            options.append(i18n.tr("很晚了，早点休息～"))
        return random.choice(options) if options else ""

    def set_pet_skin(self, name: str) -> None:
        self.store.set_pet_skin(name)
        if hasattr(self, "ball") and self.ball.winfo_exists():
            self.ball.reload_art()

    def ball_detail(self) -> str:
        run, wait, done, bad = self._counts_for(None)
        english = i18n.language.english
        if english:
            lines = [f"Run {run}    Queue {wait}", f"Done {done}    Fail {bad}"]
        else:
            lines = [f"运行 {run}    排队 {wait}", f"完成 {done}    报错 {bad}"]
        for account in self.store.accounts():
            one_run, one_wait, one_done, one_bad = self._counts_for(account["id"])
            if one_run + one_wait + one_done + one_bad == 0 and account["id"] not in self.account_results:
                continue
            name = self.tab_name(account["id"])
            if english:
                lines.append(f"{name}  run {one_run} queue {one_wait} done {one_done} fail {one_bad}")
            else:
                lines.append(f"{name}  运行{one_run} 排队{one_wait} 完成{one_done} 报错{one_bad}")
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
                self.count_var.set(i18n.tr(f"下次自动刷新 {minutes:02d}:{seconds:02d}"))
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
            lines.append(("ok", f"{title}  {result.username}@{result.host}:{result.port}  {i18n.counts(run, wait, done, bad)}{note}"))
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
        self.meta_var.set(i18n.tr(f"上次刷新 {self.last_stamp}"))
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
        done = sum(1 for job in jobs if job_bucket(job) == "done")
        bad = sum(1 for job in jobs if job_bucket(job) == "bad")
        if hasattr(self, "ball") and self._in_ball:
            if done:
                self.ball.celebrate("done", done)
            elif bad:
                self.ball.celebrate("bad", bad)
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
                return i18n.tr(f"账号{index}")
        return i18n.tr("账号")

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
            i18n.apply(menu)
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _tab_title(self, key: str) -> str:
        if key == "all":
            return i18n.tr("全部")
        for index, account in enumerate(self.store.accounts(), start=1):
            if account["id"] == key:
                label = (account.get("label") or "").strip()
                username = account.get("username") or ""
                if label and label != username:
                    return i18n.tr(f"账号{index}  {label}")
                return i18n.tr(f"账号{index}")
        return i18n.tr("账号")

    def _tab_subtitle(self, key: str) -> str:
        if key == "all":
            run, wait, done, bad = self._counts_for(None)
            return i18n.tr(f"{run + wait + done + bad} 个作业")
        result = self.account_results.get(key)
        if result and result.error:
            return i18n.tr("无密码") if _setup_gap(result.error) else i18n.tr("未连上")
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
            run, wait, done, bad = self.ball_numbers()
            self.ball.render(run, wait, done, bad)
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
            self.filter_buttons[key].configure(text=f"{i18n.tr(title)} {counts[key]}")
        self._style_filters()
        if self.sort_col:
            rows.sort(key=lambda job: _column_value(self.sort_col or "", job), reverse=self.sort_desc)
        else:
            rows.sort(key=lambda job: job.submit or "", reverse=True)
            rows.sort(key=lambda job: {"run": 0, "wait": 1, "other": 2, "bad": 3, "done": 4}.get(job_bucket(job), 5))
        for cid, title, _width, _stretch in COLUMNS:
            mark = " ↓" if self.sort_col == cid and self.sort_desc else " ↑" if self.sort_col == cid else ""
            self.tree.heading(cid, text=i18n.tr(title) + mark, command=lambda column=cid: self.on_sort(column))
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
        i18n.apply(self.menu)
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
        i18n.apply(self.menu)
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


def _ball_selftest() -> None:
    """Diagnostic used by the packaged build: collapse to the ball and write a report."""
    report_path = Path(os.environ.get("TEMP", ".")) / "jobdesk_balltest.txt"
    lines: list[str] = []

    def log(text: str) -> None:
        lines.append(text)

    def dump() -> None:
        report_path.write_text("\n".join(lines), encoding="utf-8")

    try:
        name = last_user_name()
        store = Store(user_folder(name))
        window = App(store=store, user_name=name)

        def on_error(exc, val, tb) -> None:
            log("TK-EXC: " + "".join(traceback.format_exception(exc, val, tb)))

        window.report_callback_exception = on_error

        def collapse() -> None:
            try:
                window.minimize_to_ball()
                log("collapsed ok")
            except Exception:
                log("COLLAPSE-EXC:\n" + traceback.format_exc())

        def report() -> None:
            ball = getattr(window, "ball", None)
            if ball is not None:
                log(f"fish.ready={ball.fish.ready} actions={len(ball.fish.actions)} folder={ball.fish.folder}")
                log(f"mode={ball._mode} size={ball._win_w}x{ball._win_h} mapped={ball.winfo_ismapped()} viewable={ball.winfo_viewable()}")
                log(f"pos={ball.winfo_x()},{ball.winfo_y()} items={len(ball.canvas.find_all())}")
                log(f"action={ball._action} bbox={ball._fish_bbox} photo={ball._photo is not None}")
            dump()
            window.destroy()

        window.after(700, collapse)
        window.after(4000, report)
        window.mainloop()
    except Exception:
        log("FATAL:\n" + traceback.format_exc())
    dump()


def main() -> None:
    if "--ball-selftest" in sys.argv:
        _ball_selftest()
        return
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
