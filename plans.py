"""Sticky-note planner: today, this week, this month, this term."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import date, datetime, timedelta

import tkinter as tk
from tkinter import messagebox, ttk

from ask import AskError, organize_plans
from theme import is_light, palette, readable_on
from winsecret import SecretError

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
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)

HORIZONS = (
    ("today", "今日"),
    ("week", "本周"),
    ("month", "本月"),
    ("term", "本学期"),
)
HORIZON_LABEL = dict(HORIZONS)
LABEL_HORIZON = {label: key for key, label in HORIZONS}
HORIZON_ALIAS = {
    "today": "today",
    "今日": "today",
    "今天": "today",
    "week": "week",
    "本周": "week",
    "这周": "week",
    "month": "month",
    "本月": "month",
    "这个月": "month",
    "term": "term",
    "本学期": "term",
    "学期": "term",
}
STATUSES = (
    ("todo", "待做"),
    ("doing", "进行中"),
    ("done", "完成"),
    ("paused", "暂停"),
)
STATUS_MARKS = (
    ("todo", "○"),
    ("doing", "▶"),
    ("done", "✓"),
    ("paused", "‖"),
)
STATUS_LABEL = dict(STATUSES)
RANKS = (
    ("normal", "普通"),
    ("high", "重要"),
    ("urgent", "紧急"),
)
RANK_LABEL = dict(RANKS)
BOARD_FILTERS = (
    ("open", "未完成"),
    ("today", "今日"),
    ("doing", "进行中"),
    ("week", "本周"),
    ("month", "本月"),
    ("term", "本学期"),
)
REMIND_CHOICES = (
    (15, "15 分钟"),
    (30, "30 分钟"),
    (60, "1 小时"),
    (120, "2 小时"),
    (0, "不提醒"),
)
NOTE_COLORS = {
    "todo": ("#3a3220", "#ffe7ad", WARN),
    "doing": ("#1c2740", "#d6e2ff", ACCENT),
    "done": ("#173226", "#b7e7cf", OK),
    "paused": ("#2a3140", "#b7c0d0", MUTED),
}
LIGHT_NOTES = {
    "todo": ("#f6edd4", "#5c4510", "#c4a15a"),
    "doing": ("#e7eef8", "#243656", "#8aa0c8"),
    "done": ("#e3f0e4", "#24543a", "#7eae8c"),
    "paused": ("#eeeae4", "#5c564e", "#c4b8aa"),
}


def note_colors(status: str) -> tuple[str, str, str]:
    table = LIGHT_NOTES if is_light() else NOTE_COLORS
    return table.get(status) or table["todo"]


def due_plans(plans: list[dict], today: date) -> list[dict]:
    ranked = []
    for plan in plans:
        status = plan.get("status") or "todo"
        if status in {"done", "paused"} or plan.get("trashed"):
            continue
        horizon = plan.get("horizon") or "week"
        due = _parse_day(str(plan.get("due") or ""))
        overdue = bool(due and due < today)
        due_today = horizon == "today" or bool(due and due == today)
        if not (overdue or due_today or status == "doing"):
            continue
        rank = 0 if overdue else 1 if due_today else 2
        ranked.append((rank, str(plan.get("title") or ""), plan))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]


def parse_plan_reply(text: str) -> list[dict]:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("没有找到任务清单。")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("清单格式不对。") from exc
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("清单格式不对。")
    cleaned = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        horizon = HORIZON_ALIAS.get(str(item.get("horizon") or "").strip(), "week")
        detail = str(item.get("detail") or "").strip()[:500]
        due = str(item.get("due") or "").strip()
        if _parse_day(due) is None:
            due = ""
        cleaned.append({"title": title[:80], "horizon": horizon, "detail": detail, "due": due, "status": "todo"})
        if len(cleaned) >= 12:
            break
    if not cleaned:
        raise ValueError("没有整理出任务。")
    return cleaned


def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def week_label(today: date) -> str:
    start, end = week_bounds(today)
    return f"本周    {start.month}月{start.day}日–{end.month}月{end.day}日"


def month_label(today: date) -> str:
    return f"本月    {today.year}年{today.month}月"


def plan_nodes(plan: dict) -> list[dict]:
    nodes = []
    for index, item in enumerate(plan.get("log") or []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        nodes.append(
            {
                "id": str(item.get("id") or f"n{index}"),
                "text": text,
                "at": str(item.get("at") or ""),
                "done": bool(item.get("done")),
                "parent": str(item.get("parent") or ""),
            }
        )
    if nodes:
        return nodes
    detail = str(plan.get("detail") or "").strip()
    if detail:
        return [{"id": "detail", "text": detail, "at": "", "done": False, "parent": ""}]
    return []


def split_nodes(nodes: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    ids = {node["id"] for node in nodes}
    children: dict[str, list[dict]] = {node["id"]: [] for node in nodes}
    roots = []
    for node in nodes:
        parent = str(node.get("parent") or "")
        if parent in ids and parent != node["id"]:
            children[parent].append(node)
        else:
            roots.append(node)
    return roots, children


def horizon_for(day: date, today: date) -> str:
    if day == today:
        return "today"
    if day.isocalendar()[:2] == today.isocalendar()[:2]:
        return "week"
    if (day.year, day.month) == (today.year, today.month):
        return "month"
    return "term"


def month_end(day: date) -> date:
    first_next = date(day.year + (day.month == 12), (day.month % 12) + 1, 1)
    return first_next - timedelta(days=1)


def due_presets(today: date) -> list[tuple[str, date]]:
    """Quick reschedule targets, nearest first."""
    week_start, _week_end = week_bounds(today)
    next_monday = week_start + timedelta(days=7)
    return [
        ("今天", today),
        ("明天", today + timedelta(days=1)),
        ("后天", today + timedelta(days=2)),
        ("三天后", today + timedelta(days=3)),
        ("一周后", today + timedelta(days=7)),
        ("下周一", next_monday),
        ("两周后", today + timedelta(days=14)),
        ("本月末", month_end(today)),
    ]


def _parse_day(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text or ""):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def notes_from_words(text: str, day: str) -> list[dict]:
    """Turn the user's own sentences into notes when the model returns nothing."""
    pieces: list[str] = []
    for part in re.split(r"[\n\r;；。]+", text or ""):
        piece = part.strip(" \t,，、")
        if not piece:
            continue
        bits = [bit.strip() for bit in piece.split("、") if bit.strip()]
        if len(bits) > 1 and len(piece) <= 80:
            pieces.extend(bits)
        else:
            pieces.append(piece)
    notes = []
    for piece in pieces[:12]:
        title = piece if len(piece) <= 24 else piece[:24]
        detail = "" if piece == title else piece
        notes.append({"title": title, "detail": detail, "due": day, "horizon": "today", "status": "todo"})
    return notes


def center_on(window, owner, width: int, height: int) -> None:
    """Place a window in the middle of the owner, staying on the screen."""
    window.update_idletasks()
    try:
        ox = int(owner.winfo_rootx())
        oy = int(owner.winfo_rooty())
        ow = int(owner.winfo_width())
        oh = int(owner.winfo_height())
    except tk.TclError:
        ox = oy = 0
        ow = oh = 0
    if ow < 80 or oh < 80:
        ox = oy = 0
        ow = window.winfo_screenwidth()
        oh = window.winfo_screenheight()
    x = ox + max(0, (ow - width) // 2)
    y = oy + max(0, (oh - height) // 2)
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()
    x = min(max(0, x), max(0, sw - width))
    y = min(max(0, y), max(0, sh - height))
    window.geometry(f"{width}x{height}+{x}+{y}")


def tell(owner, title: str, text: str) -> None:
    win = tk.Toplevel(owner)
    win.withdraw()
    win.title(title)
    win.configure(bg=BG)
    win.transient(owner)
    tk.Label(win, text=text, bg=BG, fg=FG, font=FONT, wraplength=360, justify="left").pack(padx=18, pady=(16, 10))
    ttk.Button(win, text="确定", command=win.destroy).pack(pady=(0, 14))
    win.update_idletasks()
    center_on(win, owner, max(360, win.winfo_reqwidth() + 8), max(120, win.winfo_reqheight() + 8))
    win.deiconify()
    win.grab_set()
    win.focus_set()


def _latest_progress(plan: dict) -> str:
    log = plan.get("log") or []
    if not isinstance(log, list) or not log:
        return ""
    last = log[-1]
    if not isinstance(last, dict):
        return ""
    return str(last.get("text") or "").strip()


class PlanBoard(tk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, bg=BG)
        self.app = app
        self.organizing = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        today = date.today()
        self.selected = today
        self.view_year = today.year
        self.view_month = today.month
        self._loaded_day = ""
        self._save_job = None
        self.quick_var = tk.StringVar()
        self.day_title = tk.StringVar(value="今天")
        self.remind_var = tk.StringVar()
        self.show_done = tk.BooleanVar(value=app.store.show_done_plans())
        self.board_filter = "today"
        self.view_mode = "list" if app.store.plan_view() == "list" else "notes"
        self.expanded: set[str] = set()
        self.filter_buttons: dict[str, tk.Button] = {}

        top = tk.Frame(self, bg=BG)
        top.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        tk.Label(top, text="管家", bg=BG, fg=FG, font=("Microsoft YaHei UI", 16, "bold")).pack(side="left", padx=(0, 12))

        views = tk.Frame(top, bg=BG)
        views.pack(side="left")
        self.note_view_btn = tk.Button(views, text="便利贴", command=lambda: self._set_view("notes"), bg=PANEL, fg=FG, activebackground=CARD, activeforeground=FG, relief="flat", bd=0, font=FONT_SMALL, padx=10, pady=3, cursor="hand2")
        self.note_view_btn.pack(side="left", padx=(0, 4))
        self.list_view_btn = tk.Button(views, text="列表", command=lambda: self._set_view("list"), bg=PANEL, fg=FG, activebackground=CARD, activeforeground=FG, relief="flat", bd=0, font=FONT_SMALL, padx=10, pady=3, cursor="hand2")
        self.list_view_btn.pack(side="left")

        tk.Frame(top, bg=LINE, width=1, height=20).pack(side="left", padx=10)

        chips = tk.Frame(top, bg=BG)
        chips.pack(side="left")
        for key, label in BOARD_FILTERS:
            button = tk.Button(
                chips,
                text=label,
                command=lambda name=key: self._select_filter(name),
                bg=PANEL,
                fg=FG,
                activebackground=CARD,
                activeforeground=FG,
                relief="flat",
                bd=0,
                font=FONT_SMALL,
                padx=8,
                pady=3,
                cursor="hand2",
            )
            button.pack(side="left", padx=2)
            self.filter_buttons[key] = button

        tk.Frame(top, bg=LINE, width=1, height=20).pack(side="left", padx=10)

        scopes = tk.Frame(top, bg=BG)
        scopes.pack(side="left")
        self.archive_btn = tk.Button(scopes, text="档案", command=lambda: self._select_filter("archive"), bg=PANEL, fg=FG, activebackground=CARD, activeforeground=FG, relief="flat", bd=0, font=FONT_SMALL, padx=8, pady=3, cursor="hand2")
        self.archive_btn.pack(side="left", padx=(0, 4))
        self.trash_btn = tk.Button(scopes, text="垃圾桶", command=lambda: self._select_filter("trash"), bg=PANEL, fg=FG, activebackground=CARD, activeforeground=FG, relief="flat", bd=0, font=FONT_SMALL, padx=8, pady=3, cursor="hand2")
        self.trash_btn.pack(side="left")

        tk.Label(top, text="提醒", bg=BG, fg=MUTED, font=FONT_SMALL).pack(side="right", padx=(0, 6))
        self.remind_box = ttk.Combobox(top, width=8, state="readonly", textvariable=self.remind_var, values=[label for _minutes, label in REMIND_CHOICES])
        self.remind_box.pack(side="right", padx=(0, 12))
        self.remind_box.bind("<<ComboboxSelected>>", self._on_remind)
        current = app.store.plan_remind_minutes()
        self.remind_var.set(dict(REMIND_CHOICES).get(current, "30 分钟"))

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        editor = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=14, pady=12)
        editor.grid(row=0, column=0, sticky="nsew")
        editor.rowconfigure(1, weight=1)
        editor.columnconfigure(0, weight=1)
        heading = tk.Frame(editor, bg=CARD)
        heading.grid(row=0, column=0, sticky="ew")
        tk.Label(heading, textvariable=self.day_title, bg=CARD, fg=FG, font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        tk.Button(heading, text="选择日期", command=self.open_calendar, bg=PANEL, fg=FG, activebackground=CARD, activeforeground=FG, relief="flat", font=FONT_SMALL, padx=10, pady=2).pack(side="left", padx=(12, 0))
        board = tk.Frame(editor, bg=CARD)
        board.grid(row=1, column=0, sticky="nsew", pady=(10, 8))
        board.rowconfigure(0, weight=1)
        board.columnconfigure(0, weight=1)
        self.note_canvas = tk.Canvas(board, bg=CARD, highlightthickness=0)
        self.note_canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(board, orient="vertical", command=self.note_canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.note_canvas.configure(yscrollcommand=scroll.set)
        self.note_canvas.bind("<MouseWheel>", lambda event: self.note_canvas.yview_scroll(int(-event.delta / 120), "units"))
        quick = tk.Frame(editor, bg=CARD)
        quick.grid(row=2, column=0, sticky="ew")
        quick_entry = tk.Entry(quick, textvariable=self.quick_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        quick_entry.pack(side="left", fill="x", expand=True, ipady=4)
        quick_entry.bind("<Return>", lambda _event: self.add_plan())
        self.quick_btn = ttk.Button(quick, text="加到这一天", style="Accent.TButton", command=self.add_plan)
        self.quick_btn.pack(side="left", padx=(8, 0))
        ask = tk.Frame(editor, bg=CARD)
        ask.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        tk.Label(ask, text="写下一段话，DeepSeek 会整理成可以直接做的任务列表。", bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")
        self.talk_box = tk.Text(ask, height=3, wrap="word", bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT, padx=8, pady=6)
        self.talk_box.pack(fill="x", pady=(4, 6))
        ask_bar = tk.Frame(ask, bg=CARD)
        ask_bar.pack(fill="x")
        self.organize_btn = ttk.Button(ask_bar, text="整理成任务", style="Accent.TButton", command=self.organize)
        self.organize_btn.pack(side="left")
        ttk.Button(ask_bar, text="密钥", style="Ghost.TButton", command=self.app.open_settings).pack(side="left", padx=(8, 0))
        self.organize_note = tk.StringVar(value="")
        tk.Label(ask_bar, textvariable=self.organize_note, bg=CARD, fg=MUTED, font=FONT_SMALL).pack(side="left", padx=(10, 0))
        self.cal_popup = None

    def reload(self) -> None:
        self._save_current_day()
        plans = self.app.store.plans()
        self._style_filters(plans)
        self._load_day_text()
        self._paint_day_tasks(plans)
        self.app.refresh_plan_badge()

    def _select_filter(self, key: str) -> None:
        self.board_filter = key
        if key == "today":
            self.selected = date.today()
            self.view_year = self.selected.year
            self.view_month = self.selected.month
        self.reload()

    def _style_filters(self, plans: list[dict]) -> None:
        alive = [plan for plan in plans if not plan.get("trashed")]
        counts = {
            "open": sum(1 for plan in alive if (plan.get("status") or "todo") in {"todo", "doing"}),
            "today": len(self._plans_on(plans, date.today())),
            "doing": sum(1 for plan in alive if (plan.get("status") or "") == "doing"),
            "week": len(self._plans_for_fold("week", plans)),
            "month": len(self._plans_for_fold("month", plans)),
            "term": len(self._plans_for_fold("term", plans)),
        }
        for key, label in BOARD_FILTERS:
            if key == "today" and self.selected != date.today():
                label = f"{self.selected.month}月{self.selected.day}日"
            button = self.filter_buttons[key]
            chosen = key == self.board_filter
            button.configure(
                text=f"{label} {counts[key]}",
                bg=ACCENT if chosen else PANEL,
                fg=palette.on_accent if chosen else FG,
                activebackground=ACCENT if chosen else CARD,
                activeforeground=palette.on_accent if chosen else FG,
            )
        archive_count = sum(1 for plan in alive if (plan.get("status") or "") == "done")
        trash_count = sum(1 for plan in plans if plan.get("trashed"))
        self._paint_side(self.archive_btn, "archive", f"档案 {archive_count}")
        self._paint_side(self.trash_btn, "trash", f"垃圾桶 {trash_count}")
        self._style_views()

    def _paint_side(self, button: tk.Button, key: str, text: str) -> None:
        chosen = self.board_filter == key
        button.configure(text=text, bg=ACCENT if chosen else PANEL, fg=palette.on_accent if chosen else FG, activebackground=ACCENT if chosen else CARD, activeforeground=palette.on_accent if chosen else FG)

    def _style_views(self) -> None:
        notes = self.view_mode != "list"
        self.note_view_btn.configure(bg=ACCENT if notes else PANEL, fg=palette.on_accent if notes else FG)
        self.list_view_btn.configure(bg=ACCENT if not notes else PANEL, fg=palette.on_accent if not notes else FG)

    def _set_view(self, mode: str) -> None:
        self.view_mode = "list" if mode == "list" else "notes"
        self.app.store.set_plan_view(self.view_mode)
        self._style_views()
        self._paint_day_tasks(self.app.store.plans())

    def _marked_days(self) -> set[str]:
        raw = self.app.store.data.get("day_notes")
        marks = {str(day) for day, text in raw.items() if text} if isinstance(raw, dict) else set()
        for plan in self.app.store.plans():
            due = str(plan.get("due") or "")
            if _parse_day(due):
                marks.add(due)
        return marks

    def open_calendar(self) -> None:
        popup = self.cal_popup
        if popup is not None:
            try:
                if popup.winfo_exists():
                    popup.destroy()
                    self.cal_popup = None
                    return
            except tk.TclError:
                pass
        popup = tk.Toplevel(self)
        popup.withdraw()
        popup.title("选择日期")
        popup.configure(bg=CARD)
        popup.transient(self.app)
        self.cal_popup = popup
        self.cal_host = tk.Frame(popup, bg=CARD, padx=12, pady=12)
        self.cal_host.pack()
        self.view_year = self.selected.year
        self.view_month = self.selected.month
        self._draw_month()
        popup.update_idletasks()
        center_on(popup, self.app, max(280, popup.winfo_reqwidth()), max(260, popup.winfo_reqheight()))
        popup.deiconify()
        popup.protocol("WM_DELETE_WINDOW", lambda: self._close_calendar())

    def _close_calendar(self) -> None:
        popup = self.cal_popup
        self.cal_popup = None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

    def _draw_month(self) -> None:
        for child in self.cal_host.winfo_children():
            child.destroy()
        nav = tk.Frame(self.cal_host, bg=CARD)
        nav.pack(fill="x", pady=(0, 6))
        tk.Button(nav, text="‹", command=lambda: self._shift_month(-1), bg=PANEL, fg=FG, relief="flat", font=FONT, padx=8).pack(side="left")
        tk.Label(nav, text=f"{self.view_year}年{self.view_month}月", bg=CARD, fg=FG, font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=8)
        tk.Button(nav, text="›", command=lambda: self._shift_month(1), bg=PANEL, fg=FG, relief="flat", font=FONT, padx=8).pack(side="left")
        tk.Button(nav, text="今天", command=lambda: self.pick(date.today()), bg=PANEL, fg=FG, relief="flat", font=FONT_SMALL, padx=8).pack(side="right")
        week = tk.Frame(self.cal_host, bg=CARD)
        week.pack(fill="x")
        for name in "一二三四五六日":
            tk.Label(week, text=name, bg=CARD, fg=MUTED, font=FONT_SMALL, width=4).pack(side="left")
        grid = tk.Frame(self.cal_host, bg=CARD)
        grid.pack(fill="x", pady=(4, 0))
        first = date(self.view_year, self.view_month, 1)
        start = first - timedelta(days=first.weekday())
        marks = self._marked_days()
        today = date.today()
        for row in range(6):
            for col in range(7):
                day = start + timedelta(days=row * 7 + col)
                selected = day == self.selected
                bg = ACCENT if selected else HEADING if day == today else CARD
                fg = palette.on_accent if selected else FG if day.month == self.view_month else MUTED
                text = f"{day.day} ·" if day.isoformat() in marks else str(day.day)
                cell = tk.Label(grid, text=text, bg=bg, fg=fg, font=FONT_SMALL, width=4, pady=4, cursor="hand2")
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.bind("<Button-1>", lambda _event, item=day: self.pick(item))

    def _shift_month(self, delta: int) -> None:
        month = self.view_month + delta
        year = self.view_year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        self.view_year = year
        self.view_month = month
        self._draw_month()

    def pick(self, day: date) -> None:
        self._save_current_day()
        self.selected = day
        self.board_filter = "today"
        self.view_year = day.year
        self.view_month = day.month
        self._loaded_day = ""
        self._close_calendar()
        self.reload()

    def _heading(self, day: date) -> str:
        today = date.today()
        if day == today:
            name = "今天"
        elif day == today + timedelta(days=1):
            name = "明天"
        else:
            name = f"{day.month}月{day.day}日"
        return f"{name}    {day.isoformat()}    周{'一二三四五六日'[day.weekday()]}"

    def _load_day_text(self) -> None:
        today = date.today()
        titles = {
            "open": "未完成",
            "doing": "进行中",
            "week": week_label(today),
            "month": month_label(today),
            "term": "本学期",
            "archive": "完成档案",
            "trash": "垃圾桶",
        }
        if self.board_filter == "today":
            self.day_title.set(self._heading(self.selected))
        else:
            self.day_title.set(titles.get(self.board_filter, ""))
        add_labels = {"week": "加到本周", "month": "加到本月", "term": "加到本学期", "today": "加到这一天"}
        self.quick_btn.configure(text=add_labels.get(self.board_filter, "加一条"))
        self._loaded_day = self.selected.isoformat()

    def _save_current_day(self) -> None:
        self._save_job = None

    def _plans_on(self, plans: list[dict], day: date) -> list[dict]:
        found = []
        for plan in plans:
            if plan.get("trashed") or (plan.get("status") or "") == "done":
                continue
            due = _parse_day(str(plan.get("due") or ""))
            if due == day or (day == date.today() and plan.get("horizon") == "today" and due is None):
                found.append(plan)
        return found

    def _filtered(self, plans: list[dict]) -> list[dict]:
        key = self.board_filter
        if key == "trash":
            return [plan for plan in plans if plan.get("trashed")]
        alive = [plan for plan in plans if not plan.get("trashed")]
        if key == "archive":
            return [plan for plan in alive if (plan.get("status") or "") == "done"]
        if key == "open":
            return [plan for plan in alive if (plan.get("status") or "todo") in {"todo", "doing"}]
        if key == "doing":
            return [plan for plan in alive if (plan.get("status") or "") == "doing"]
        if key in {"week", "month", "term"}:
            return self._plans_for_fold(key, plans)
        return self._plans_on(plans, self.selected)

    def _paint_day_tasks(self, plans: list[dict]) -> None:
        yview = self.note_canvas.yview()
        for child in self.note_canvas.winfo_children():
            child.destroy()
        self.note_canvas.delete("all")
        items = self._filtered(plans)
        if not items:
            empty = {
                "open": "没有未完成的便利贴。",
                "today": "这一天还没有便利贴。",
                "doing": "没有进行中的便利贴。",
                "week": "本周还没有便利贴。",
                "month": "本月还没有便利贴。",
                "term": "本学期还没有便利贴。",
                "archive": "档案里还没有完成的任务。",
                "trash": "垃圾桶是空的。",
            }
            self.note_canvas.create_text(16, 16, text=empty.get(self.board_filter, "还没有便利贴。"), fill=MUTED, font=FONT_SMALL, anchor="nw")
            self._fit_notes()
            self._keep_view(yview)
            return
        items.sort(key=lambda plan: int(plan.get("z") or 0))
        if self.view_mode == "list":
            self._paint_list(items)
            self._keep_view(yview)
            return
        for index, plan in enumerate(items):
            self._place_note(plan, index, int(plan.get("seq") or index + 1))
        self._fit_notes()
        self._keep_view(yview)

    def _keep_view(self, yview) -> None:
        if yview and len(yview) > 1 and yview[0] > 0:
            self.note_canvas.yview_moveto(yview[0])

    def _fit_notes(self) -> None:
        box = self.note_canvas.bbox("all")
        width = max(self.note_canvas.winfo_width(), 10)
        height = max(self.note_canvas.winfo_height(), 10)
        if box:
            width = max(width, box[2] + 24)
            height = max(height, box[3] + 24)
        self.note_canvas.configure(scrollregion=(0, 0, width, height))

    def _place_note(self, plan: dict, index: int, number: int) -> None:
        status = plan.get("status") if plan.get("status") in NOTE_COLORS else "todo"
        paper, ink, mark = note_colors(status)
        rank = plan.get("importance") if plan.get("importance") in RANK_LABEL else "normal"
        x = plan.get("x")
        y = plan.get("y")
        w = plan.get("w") if isinstance(plan.get("w"), int) else 420
        h = plan.get("h") if isinstance(plan.get("h"), int) else 200
        if not isinstance(x, int) or not isinstance(y, int):
            # Lay fresh notes out in a grid instead of stacking them 36px apart.
            span = max(self.note_canvas.winfo_width(), 640)
            cols = max(1, span // (w + 16))
            x = 16 + (index % cols) * (w + 16)
            y = 16 + (index // cols) * (h + 16)
        card = tk.Frame(self.note_canvas, bg=paper, highlightthickness=1, highlightbackground=mark, bd=0)
        window = self.note_canvas.create_window(x, y, window=card, anchor="nw", width=w, height=h, tags="note")
        head = tk.Frame(card, bg=paper, cursor="fleur")
        head.pack(fill="x", padx=10, pady=(10, 0))
        badge = tk.Label(head, text=str(number), bg=mark, fg=readable_on(mark), font=("Microsoft YaHei UI", 9, "bold"), width=2, padx=2, pady=1)
        badge.pack(side="left", padx=(0, 8))
        done_mark = self._check_label(head, paper, ink, (plan.get("status") or "") == "done")
        done_mark.pack(side="left", padx=(0, 6))
        done_mark.bind("<Button-1>", lambda _event, item=plan: self._toggle_plan(item))
        title = tk.Label(head, text=plan.get("title") or "", bg=paper, fg=ink, font=("Microsoft YaHei UI", 11, "bold"), anchor="w", cursor="fleur")
        title.pack(side="left", fill="x", expand=True)
        star = tk.Label(head, text=self._star_text(rank), bg=paper, fg=self._star_color(rank), font=("Microsoft YaHei UI", 14, "bold"), cursor="hand2")
        star._plan_control = True
        star.pack(side="right")
        star.bind("<Button-1>", lambda _event, item=plan: self._cycle_rank(item))
        self._status_picks(card, plan, paper, ink, mark, status)
        chain = tk.Frame(card, bg=paper)
        chain.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        row = tk.Frame(chain, bg=paper)
        row.pack(anchor="w", fill="x")
        row.rowconfigure(0, weight=1)
        nodes = plan_nodes(plan)
        roots, children = split_nodes(nodes)
        if not roots:
            tk.Label(row, text="还没有进展", bg=paper, fg=ink, font=FONT_SMALL).grid(row=0, column=0, sticky="w")
        column = 0
        for step_index, node in enumerate(roots):
            if step_index:
                arrow = tk.Label(row, text="→", bg=paper, fg=mark, font=("Microsoft YaHei UI", 16, "bold"))
                arrow.grid(row=0, column=column, rowspan=2, sticky="ns", padx=2)
                column += 1
            box = tk.Frame(row, bg=PANEL, highlightthickness=1, highlightbackground=mark)
            box.grid(row=0, column=column, sticky="n", padx=2, pady=2)
            self._node_line(box, plan, node, paper, ink, side="left")
            branch = tk.Frame(row, bg=paper)
            branch.grid(row=1, column=column, sticky="nw")
            for child in children.get(node["id"]) or []:
                self._branch_line(branch, plan, child, children, paper, ink, mark, 0)
            column += 1
        edge_x = tk.Frame(card, bg=mark, width=8, cursor="sb_h_double_arrow")
        edge_y = tk.Frame(card, bg=mark, height=8, cursor="sb_v_double_arrow")
        edge_x._plan_control = True
        edge_y._plan_control = True
        edge_x.place(relx=1, rely=0, relheight=1, anchor="ne")
        edge_y.place(relx=0, rely=1, relwidth=1, anchor="sw")
        self._bind_note(card, plan, title)
        self._bind_wheel(card, self.note_canvas)
        title.bind("<Double-Button-1>", lambda _event, item=plan, label=title: self._rename(item, label))
        self._bind_move(head, window, plan)
        self._bind_move(title, window, plan)
        self._bind_move(badge, window, plan)
        self._bind_resize(edge_x, window, plan, "x")
        self._bind_resize(edge_y, window, plan, "y")

    def _status_picks(self, card, plan: dict, paper: str, ink: str, mark: str, status: str) -> None:
        row = tk.Frame(card, bg=paper)
        row._plan_control = True
        row.pack(side="bottom", fill="x", padx=10, pady=(0, 12))
        plan_id = plan.get("id")
        for key, glyph in STATUS_MARKS:
            chosen = key == status
            stamp = tk.Frame(
                row,
                bg=mark if chosen else paper,
                highlightthickness=1,
                highlightbackground=ink if chosen else paper,
                padx=3,
                pady=0,
                cursor="hand2",
            )
            stamp._plan_control = True
            stamp.pack(side="left", padx=(0, 4))
            icon = tk.Label(stamp, text=glyph, bg=stamp["bg"], fg=readable_on(mark) if chosen else ink, font=("Segoe UI Symbol", 10), cursor="hand2")
            icon._plan_control = True
            icon.pack()

            def choose(_event, name=key, current=status, item_id=plan_id) -> None:
                if name == current:
                    return
                self._set_status(item_id, name)

            for widget in (stamp, icon):
                widget.bind("<Button-1>", choose)
        due = _parse_day(str(plan.get("due") or ""))
        if due:
            when = tk.Label(row, text=f"{due.month}月{due.day}日", bg=paper, fg=ink, font=("Microsoft YaHei UI", 8))
            when._plan_control = True
            when.pack(side="left", padx=(6, 0))
        picker = tk.Label(row, text="改期 ▾", bg=paper, fg=ink, font=("Microsoft YaHei UI", 8), cursor="hand2", padx=2)
        picker._plan_control = True
        picker.pack(side="right", padx=(4, 0))
        picker.bind("<Button-1>", lambda event, item=plan: self._due_menu(event, item))

    def _star_text(self, rank: str) -> str:
        return {"high": "*", "urgent": "***"}.get(rank, "☆")

    def _star_color(self, rank: str) -> str:
        if rank == "urgent":
            return BAD
        if rank == "high":
            return WARN
        return MUTED

    def _check_label(self, parent, bg: str, fg: str, done: bool) -> tk.Label:
        label = tk.Label(parent, text="☑" if done else "☐", bg=bg, fg=fg, font=("Microsoft YaHei UI", 12), cursor="hand2")
        label._plan_control = True
        return label

    def _node_line(self, parent, plan: dict, node: dict, paper: str, ink: str, side: str) -> None:
        done = bool(node.get("done"))
        check = self._check_label(parent, PANEL, ink, done)
        check.pack(side=side, padx=(6, 0), pady=6)
        check.bind("<Button-1>", lambda _event, item=plan, one=node: self._toggle_node(item, one))
        text = tk.Label(parent, text=node.get("text") or "", bg=PANEL, fg=MUTED if done else ink, font=FONT_SMALL, wraplength=140, justify="left", padx=8, pady=6, anchor="w")
        text.pack(side=side)

    def _branch_line(self, parent, plan: dict, node: dict, children: dict, paper: str, ink: str, mark: str, depth: int) -> None:
        line = tk.Frame(parent, bg=paper)
        line.pack(anchor="w", padx=(12 + depth * 14, 0), pady=1)
        tk.Label(line, text="↳", bg=paper, fg=mark, font=FONT_SMALL).pack(side="left")
        box = tk.Frame(line, bg=PANEL, highlightthickness=1, highlightbackground=mark)
        box.pack(side="left", padx=(2, 0))
        self._node_line(box, plan, node, paper, ink, side="left")
        for child in children.get(node["id"]) or []:
            self._branch_line(parent, plan, child, children, paper, ink, mark, depth + 1)

    def _toggle_plan(self, plan: dict) -> None:
        status = "todo" if (plan.get("status") or "") == "done" else "done"
        self.app.store.set_plan_status(str(plan.get("id") or ""), status)
        self.reload()

    def _toggle_node(self, plan: dict, node: dict) -> None:
        self.app.store.set_node_done(str(plan.get("id") or ""), str(node.get("id") or ""), not bool(node.get("done")))
        self.reload()

    def _cycle_rank(self, plan: dict) -> None:
        rank = plan.get("importance") if plan.get("importance") in RANK_LABEL else "normal"
        nxt = {"normal": "high", "high": "urgent", "urgent": "normal"}[rank]
        self._set_rank(str(plan.get("id") or ""), nxt)

    def _bind_note(self, widget, plan: dict, title: tk.Label) -> None:
        if getattr(widget, "_plan_control", False):
            return
        widget.bind("<Button-3>", lambda event, item=plan, label=title: self._note_menu(event, item, label))
        widget.bind("<Double-Button-1>", lambda _event, item=plan: self.edit_plan(item))
        for child in widget.winfo_children():
            self._bind_note(child, plan, title)

    def _note_menu(self, event, plan: dict, title: tk.Label) -> None:
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        menu.add_command(label="上移一层", command=lambda item=plan: self._stack(item, "up"))
        menu.add_command(label="下移一层", command=lambda item=plan: self._stack(item, "down"))
        menu.add_command(label="放到最前", command=lambda item=plan: self._stack(item, "top"))
        menu.add_command(label="放到最后", command=lambda item=plan: self._stack(item, "bottom"))
        menu.add_separator()
        menu.add_command(label="编辑内容", command=lambda item=plan: self.edit_plan(item))
        menu.add_command(label="改标题", command=lambda item=plan, label=title: self._rename(item, label))
        due_menu = tk.Menu(menu, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for label, target in due_presets(date.today()):
            due_menu.add_command(
                label=f"{label}    {target.month}月{target.day}日",
                command=lambda day=target, item=plan: self._set_due(item, day),
            )
        due_menu.add_separator()
        due_menu.add_command(label="自定义日期…", command=lambda item=plan: self._ask_due(item))
        menu.add_cascade(label="改期", menu=due_menu)
        status_menu = tk.Menu(menu, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for key, label in STATUSES:
            status_menu.add_command(label=label, command=lambda name=key, item=plan: self._set_status(item.get("id"), name))
        menu.add_cascade(label="状态", menu=status_menu)
        rank_menu = tk.Menu(menu, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for key, label in RANKS:
            rank_menu.add_command(label=label, command=lambda name=key, item=plan: self._set_rank(item.get("id"), name))
        menu.add_cascade(label="重要性", menu=rank_menu)
        menu.add_separator()
        if plan.get("trashed"):
            menu.add_command(label="恢复", command=lambda item=plan: self._restore_note(item))
            menu.add_command(label="彻底删除", command=lambda item=plan: self._purge_note(item))
        else:
            menu.add_command(label="放进垃圾桶", command=lambda item=plan: self._trash_note(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _stack(self, plan: dict, how: str) -> None:
        self.app.store.stack_plan(str(plan.get("id") or ""), how)
        self.reload()

    def _rename(self, plan: dict, title: tk.Label) -> str:
        parent = title.master
        entry = tk.Entry(parent, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=("Microsoft YaHei UI", 11, "bold"), highlightthickness=1, highlightbackground=ACCENT)
        entry.insert(0, plan.get("title") or "")
        entry.pack(side="left", fill="x", expand=True)
        title.pack_forget()
        state = {"done": False}

        def finish(_event=None) -> None:
            if state["done"]:
                return
            state["done"] = True
            text = entry.get().strip()
            entry.destroy()
            if text and text != (plan.get("title") or ""):
                self._save_title(plan, text)
                return
            if title.winfo_exists():
                title.pack(side="left", fill="x", expand=True)

        entry.bind("<Return>", finish)
        entry.bind("<Escape>", lambda _event: (state.update(done=True), entry.destroy(), title.pack(side="left", fill="x", expand=True)))
        entry.bind("<FocusOut>", finish)
        entry.focus_set()
        entry.select_range(0, "end")
        return "break"

    def _save_title(self, plan: dict, title: str) -> None:
        self.app.store.upsert_plan(
            {
                "id": plan.get("id"),
                "title": title,
                "horizon": plan.get("horizon") or "today",
                "status": plan.get("status") or "todo",
                "detail": plan.get("detail") or "",
                "due": plan.get("due") or "",
            }
        )
        self.reload()

    def _set_rank(self, plan_id: str, importance: str) -> None:
        self.app.store.set_plan_importance(plan_id, importance)
        self.reload()

    def _trash_note(self, plan: dict) -> None:
        self.app.store.trash_plan(str(plan.get("id") or ""))
        self.reload()

    def _restore_note(self, plan: dict) -> None:
        self.app.store.restore_plan(str(plan.get("id") or ""))
        self.reload()

    def _purge_note(self, plan: dict) -> None:
        if not messagebox.askyesno("彻底删除", "这张便利贴会从垃圾桶里删掉，不能恢复。", parent=self.app):
            return
        self.app.store.delete_plan(str(plan.get("id") or ""))
        self.reload()

    def _bind_move(self, widget, window: int, plan: dict) -> None:
        state = {"x": 0, "y": 0, "ox": 0, "oy": 0, "moved": False}

        def press(event) -> None:
            state["x"] = event.x_root
            state["y"] = event.y_root
            origin = self.note_canvas.coords(window)
            state["ox"] = origin[0] if origin else 0
            state["oy"] = origin[1] if len(origin) > 1 else 0
            state["moved"] = False

        def motion(event) -> None:
            dx = event.x_root - state["x"]
            dy = event.y_root - state["y"]
            if abs(dx) > 3 or abs(dy) > 3:
                state["moved"] = True
            self.note_canvas.coords(window, max(0, state["ox"] + dx), max(0, state["oy"] + dy))
            self._fit_notes()

        def release(_event) -> None:
            if not state["moved"]:
                return
            origin = self.note_canvas.coords(window)
            if len(origin) < 2:
                return
            width = int(float(self.note_canvas.itemcget(window, "width")))
            height = int(float(self.note_canvas.itemcget(window, "height")))
            self.app.store.place_plan(str(plan.get("id") or ""), int(origin[0]), int(origin[1]), width, height)
            plan["x"], plan["y"], plan["w"], plan["h"] = int(origin[0]), int(origin[1]), width, height

        widget.bind("<Button-1>", press)
        widget.bind("<B1-Motion>", motion)
        widget.bind("<ButtonRelease-1>", release)

    def _bind_resize(self, widget, window: int, plan: dict, axis: str) -> None:
        state = {"x": 0, "y": 0, "w": 420, "h": 176}

        def press(event) -> str:
            state["x"] = event.x_root
            state["y"] = event.y_root
            state["w"] = int(float(self.note_canvas.itemcget(window, "width")))
            state["h"] = int(float(self.note_canvas.itemcget(window, "height")))
            return "break"

        def motion(event) -> str:
            width = state["w"]
            height = state["h"]
            if axis == "x":
                width = max(240, state["w"] + event.x_root - state["x"])
            else:
                height = max(160, state["h"] + event.y_root - state["y"])
            self.note_canvas.itemconfigure(window, width=width, height=height)
            self._fit_notes()
            return "break"

        def release(_event) -> None:
            origin = self.note_canvas.coords(window)
            if len(origin) < 2:
                return
            width = int(float(self.note_canvas.itemcget(window, "width")))
            height = int(float(self.note_canvas.itemcget(window, "height")))
            self.app.store.place_plan(str(plan.get("id") or ""), int(origin[0]), int(origin[1]), width, height)
            plan["x"], plan["y"], plan["w"], plan["h"] = int(origin[0]), int(origin[1]), width, height

        widget.bind("<Button-1>", press)
        widget.bind("<B1-Motion>", motion)
        widget.bind("<ButtonRelease-1>", release)

    def _plans_for_fold(self, key: str, plans: list[dict]) -> list[dict]:
        today = date.today()
        week_start, week_end = week_bounds(today)
        found = []
        for plan in plans:
            if plan.get("trashed") or (plan.get("status") or "") == "done":
                continue
            due = _parse_day(str(plan.get("due") or ""))
            horizon = plan.get("horizon") or ""
            if key == "week" and (horizon == "week" or (due is not None and week_start <= due <= week_end)):
                found.append(plan)
            elif key == "month" and (horizon == "month" or (due is not None and due.year == today.year and due.month == today.month)):
                found.append(plan)
            elif key == "term" and horizon == "term":
                found.append(plan)
        return found

    def _paint_list(self, items: list[dict]) -> None:
        host = tk.Frame(self.note_canvas, bg=CARD)
        width = max(self.note_canvas.winfo_width() - 28, 520)
        self.note_canvas.create_window(8, 8, window=host, anchor="nw", width=width, tags="note")
        for plan in items:
            self._list_plan(host, plan)
        host.update_idletasks()
        self._fit_notes()

    def _list_plan(self, parent, plan: dict) -> None:
        plan_id = str(plan.get("id") or "")
        rank = plan.get("importance") if plan.get("importance") in RANK_LABEL else "normal"
        open_now = plan_id in self.expanded
        row = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=8, pady=6)
        row.pack(fill="x", pady=4)
        number = tk.Label(row, text=str(plan.get("seq") or ""), bg=PANEL, fg=MUTED, font=FONT_SMALL, width=3, anchor="e")
        number.pack(side="left")
        arrow = tk.Label(row, text="▾" if open_now else "▸", bg=PANEL, fg=FG, font=FONT, width=2, cursor="hand2")
        arrow.pack(side="left")
        done = (plan.get("status") or "") == "done"
        check = self._check_label(row, PANEL, FG, done)
        check.pack(side="left")
        check.bind("<Button-1>", lambda _event, item=plan: self._toggle_plan(item))
        title = tk.Label(row, text=plan.get("title") or "", bg=PANEL, fg=FG, font=("Microsoft YaHei UI", 11, "bold"), anchor="w", cursor="hand2")
        title.pack(side="left", fill="x", expand=True, padx=6)
        star = tk.Label(row, text=self._star_text(rank), bg=PANEL, fg=self._star_color(rank), font=("Microsoft YaHei UI", 14, "bold"), cursor="hand2")
        star._plan_control = True
        star.pack(side="right")
        star.bind("<Button-1>", lambda _event, item=plan: self._cycle_rank(item))
        arrow.bind("<Button-1>", lambda _event, item=plan: self._toggle_open(item))
        for widget in (arrow, title, row, number):
            widget.bind("<Double-Button-1>", lambda _event, item=plan: self.edit_plan(item))
            widget.bind("<Button-3>", lambda event, item=plan, label=title: self._note_menu(event, item, label))
        if not open_now:
            return
        nodes = plan_nodes(plan)
        roots, children = split_nodes(nodes)
        if not roots:
            tk.Label(parent, text="还没有子任务。双击这行可以写。", bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", padx=36, pady=(0, 6))
            return
        for node in roots:
            self._list_node(parent, plan, node, children, 0)

    def _list_node(self, parent, plan: dict, node: dict, children: dict, depth: int) -> None:
        done = bool(node.get("done"))
        line = tk.Frame(parent, bg=CARD)
        line.pack(fill="x", padx=(28 + depth * 18, 12), pady=1)
        prefix = "↳" if depth else "→"
        tk.Label(line, text=prefix, bg=CARD, fg=MUTED, font=FONT_SMALL, width=2).pack(side="left")
        text = tk.Label(line, text=node.get("text") or "", bg=CARD, fg=MUTED if done else FG, font=FONT, anchor="w")
        text.pack(side="left", fill="x", expand=True)
        check = self._check_label(line, CARD, FG, done)
        check.pack(side="right")
        check.bind("<Button-1>", lambda _event, item=plan, one=node: self._toggle_node(item, one))
        for child in children.get(node["id"]) or []:
            self._list_node(parent, plan, child, children, depth + 1)

    def _toggle_open(self, plan: dict) -> None:
        plan_id = str(plan.get("id") or "")
        if plan_id in self.expanded:
            self.expanded.discard(plan_id)
        else:
            self.expanded.add(plan_id)
        self._paint_day_tasks(self.app.store.plans())

    def _note(self, parent, plan: dict) -> None:
        status = plan.get("status") if plan.get("status") in NOTE_COLORS else "todo"
        paper, ink, mark = note_colors(status)
        card = tk.Frame(parent, bg=paper, highlightthickness=1, highlightbackground=LINE, padx=14, pady=12, cursor="hand2")
        card.pack(anchor="w", pady=(0, 14), padx=(8, 40))
        bar = tk.Frame(card, bg=mark, width=4)
        bar.place(x=0, y=0, relheight=1)
        title = tk.Label(card, text=plan.get("title") or "", bg=paper, fg=ink, font=("Microsoft YaHei UI", 12, "bold"), anchor="w", justify="left", wraplength=280, cursor="hand2")
        title.pack(fill="x", padx=(8, 0))
        body = _latest_progress(plan) or str(plan.get("detail") or "").strip()
        body_label = None
        if body:
            body_label = tk.Label(card, text=body, bg=paper, fg=ink, font=FONT, anchor="w", justify="left", wraplength=280)
            body_label.pack(fill="x", padx=(8, 0), pady=(6, 0))
        actions = tk.Frame(card, bg=paper)
        actions.pack(fill="x", padx=(8, 0), pady=(8, 0))
        for key, label in STATUSES:
            chip_bg = mark if key == status else paper
            chip_fg = readable_on(mark) if key == status else ink
            chip = tk.Label(actions, text=label, bg=chip_bg, fg=chip_fg, font=("Microsoft YaHei UI", 8), padx=4, pady=1, cursor="hand2")
            chip.pack(side="left", padx=(0, 4))
            chip.bind("<Button-1>", lambda _event, plan_id=plan.get("id"), name=key: self._set_status(plan_id, name))
        for widget in (card, title, body_label):
            if widget is not None:
                widget.bind("<Button-1>", lambda _event, item=plan: self._open_plan(item))
        master = getattr(parent, "master", None)
        if master is not None and hasattr(master, "yview_scroll"):
            self._bind_wheel(card, master)

    def _open_plan(self, plan: dict) -> None:
        due = _parse_day(str(plan.get("due") or ""))
        if due and due != self.selected:
            self.pick(due)
            return
        self.edit_plan(plan)

    def _bind_wheel(self, widget, canvas) -> None:
        widget.bind("<MouseWheel>", lambda event, target=canvas: target.yview_scroll(int(-event.delta / 120), "units"))
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    def _set_status(self, plan_id: str, status: str) -> None:
        self.app.store.set_plan_status(plan_id, status)
        self.reload()

    def _push_plan(self, plan: dict, days: int) -> None:
        today = date.today()
        target = today + timedelta(days=days)
        self.app.store.set_plan_when(str(plan.get("id") or ""), target.isoformat(), horizon_for(target, today))
        self.reload()

    def _set_due(self, plan: dict, target: date) -> None:
        today = date.today()
        self.app.store.set_plan_when(str(plan.get("id") or ""), target.isoformat(), horizon_for(target, today))
        self.reload()

    def _due_menu(self, event, plan: dict) -> None:
        today = date.today()
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=FG, activebackground=ACCENT, activeforeground=palette.on_accent, font=FONT)
        for label, target in due_presets(today):
            text = label if target == today else f"{label}    {target.month}月{target.day}日"
            menu.add_command(label=text, command=lambda day=target, item=plan: self._set_due(item, day))
        menu.add_separator()
        menu.add_command(label="自定义日期…", command=lambda item=plan: self._ask_due(item))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _ask_due(self, plan: dict) -> None:
        from tkinter import simpledialog

        typed = simpledialog.askstring("改期", "写成一个日期，例如 2026-11-20", parent=self.app)
        if not typed or not typed.strip():
            return
        target = _parse_day(typed.strip())
        if target is None:
            tell(self.app, "改期", "日期要写成 2026-11-20 这样。")
            return
        self._set_due(plan, target)

    def _toggle_done(self) -> None:
        self.app.store.set_show_done_plans(self.show_done.get())
        self.reload()

    def _on_remind(self, _event=None) -> None:
        selected = self.remind_var.get()
        minutes = next((value for value, label in REMIND_CHOICES if label == selected), 30)
        self.app.store.set_plan_remind_minutes(minutes)
        self.app.store.touch_plan_remind()

    def _new_scope(self) -> tuple[str, str]:
        today = date.today()
        if self.board_filter == "week":
            return "week", today.isoformat()
        if self.board_filter == "month":
            return "month", today.isoformat()
        if self.board_filter == "term":
            return "term", today.isoformat()
        return horizon_for(self.selected, today), self.selected.isoformat()

    def add_plan(self) -> None:
        title = self.quick_var.get().strip()
        if not title:
            return
        horizon, due = self._new_scope()
        try:
            self.app.store.upsert_plan(
                {
                    "title": title,
                    "horizon": horizon,
                    "status": "todo",
                    "detail": "",
                    "due": due,
                }
            )
        except ValueError as exc:
            tell(self.app, "管家", str(exc))
            return
        self.quick_var.set("")
        self.reload()

    def edit_plan(self, plan: dict) -> None:
        ProgressSheet(self.app, plan, self.reload)

    def organize(self) -> None:
        if self.organizing:
            return
        narrative = self.talk_box.get("1.0", "end").strip()
        if not narrative:
            self.organize_note.set("先写下要做的事。")
            return
        if not self.app.store.has_api_key():
            items = notes_from_words(narrative, self.selected.isoformat())
            if items:
                self._stick(items)
            self.organize_note.set("还没有密钥，已先按原文拆开。填写后会交给 DeepSeek。")
            self.app.open_settings()
            return
        try:
            key = self.app.store.api_key()
        except SecretError as exc:
            tell(self.app, "管家", str(exc))
            return
        self.organizing = True
        self.organize_btn.configure(state="disabled")
        self.organize_note.set("正在整理…")
        self._organize_text = narrative
        base = self.app.store.api_base()
        model = self.app.store.api_model()
        day = self.selected.isoformat()

        def work() -> None:
            try:
                reply = organize_plans(base, key, model, narrative, day)
                error = ""
            except AskError as exc:
                reply = ""
                error = str(exc)
            except Exception as exc:
                reply = ""
                error = f"整理失败：{exc}"
            self.after(0, lambda: self._organized(reply, error))

        threading.Thread(target=work, daemon=True).start()

    def _organized(self, reply: str, error: str) -> None:
        self.organizing = False
        if self.winfo_exists():
            self.organize_btn.configure(state="normal")
            self.organize_note.set("")
        if error:
            self.organize_note.set(error)
            return
        day = self.selected.isoformat()
        try:
            items = parse_plan_reply(reply)
        except ValueError:
            items = notes_from_words(getattr(self, "_organize_text", ""), day)
        if not items:
            items = notes_from_words(getattr(self, "_organize_text", ""), day)
        if not items:
            tell(self.app, "管家", "没有整理出任务。")
            return
        self._stick(items)

    def _stick(self, items: list[dict]) -> None:
        day = self.selected.isoformat()
        fallback = horizon_for(self.selected, date.today())
        for item in items:
            # Keep what the model or the fallback splitter worked out; only fill blanks.
            due = _parse_day(str(item.get("due") or "")) or self.selected
            item["due"] = due.isoformat()
            if item.get("horizon") not in HORIZON_LABEL:
                item["horizon"] = fallback if due == self.selected else horizon_for(due, date.today())
            item["status"] = item.get("status") or "todo"
        self.app.store.add_plans(items)
        if hasattr(self, "talk_box"):
            self.talk_box.delete("1.0", "end")
        self.view_mode = "list"
        self.app.store.set_plan_view("list")
        self.organize_note.set(f"已整理成 {len(items)} 条任务。")
        self.reload()

    def _drafts_saved(self) -> None:
        if hasattr(self, "talk_box"):
            self.talk_box.delete("1.0", "end")
        self.reload()


class ProgressSheet(tk.Toplevel):
    """Edit earlier text, and add the next step or a branch."""

    def __init__(self, app, plan: dict, on_saved) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.plan_id = plan.get("id")
        self.on_saved = on_saved
        self.nodes = plan_nodes(plan) or [{"id": uuid.uuid4().hex[:8], "text": "", "at": "", "done": False, "parent": ""}]
        self._editors: list[dict] = []
        self.title(plan.get("title") or "便利贴")
        self.configure(bg=BG)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._close)
        pad = tk.Frame(self, bg=BG)
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        self.title_var = tk.StringVar(value=plan.get("title") or "")
        self.title_box = tk.Entry(pad, textvariable=self.title_var, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=("Microsoft YaHei UI", 14, "bold"), highlightthickness=1, highlightbackground=LINE, highlightcolor=ACCENT)
        self.title_box.pack(fill="x", ipady=4)
        tk.Label(pad, text="以前写过的都能改。下一步用箭头接上，分支从某一条分出去。", bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x", pady=(8, 6))
        self.canvas = tk.Canvas(pad, bg=BG, highlightthickness=0, height=280)
        self.canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._canvas_width = 0

        def fit_inner(_event=None) -> None:
            box = self.canvas.bbox("all")
            if box:
                self.canvas.configure(scrollregion=box)

        def fit_width(event) -> None:
            if event.widget is not self.canvas or abs(event.width - self._canvas_width) < 4:
                return
            self._canvas_width = event.width
            self.canvas.itemconfigure(self.window_id, width=event.width)

        self.inner.bind("<Configure>", fit_inner)
        self.canvas.bind("<Configure>", fit_width)
        self._paint_nodes()
        bar = tk.Frame(pad, bg=BG)
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="加下一步", style="Ghost.TButton", command=self._add_flow).pack(side="left")
        ttk.Button(bar, text="记下", style="Accent.TButton", command=self.keep).pack(side="left", padx=8)
        ttk.Button(bar, text="放进垃圾桶", style="Ghost.TButton", command=self.delete).pack(side="left")
        ttk.Button(bar, text="关闭", style="Ghost.TButton", command=self._close).pack(side="right")
        center_on(self, app, 560, 560)
        self.deiconify()
        self.grab_set()
        self.title_box.focus_set()

    def _current(self) -> dict | None:
        return next((item for item in self.app.store.plans() if item.get("id") == self.plan_id), None)

    def _read(self) -> list[dict]:
        rows = []
        for editor in self._editors:
            node = dict(editor["node"])
            node["text"] = editor["entry"].get().strip()
            node["done"] = bool(editor["done"].get())
            rows.append(node)
        return rows

    def _paint_nodes(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        self._editors = []
        roots, children = split_nodes(self.nodes)
        ordered: list[tuple[dict, int]] = []

        def walk(node: dict, depth: int) -> None:
            ordered.append((node, depth))
            for child in children.get(node["id"]) or []:
                walk(child, depth + 1)

        for node in roots:
            walk(node, 0)
        for node, depth in ordered:
            self._editor_row(node, depth)

    def _editor_row(self, node: dict, depth: int) -> None:
        row = tk.Frame(self.inner, bg=BG)
        row.pack(fill="x", pady=3, padx=(depth * 22, 0))
        mark = "↳" if depth else "→"
        tk.Label(row, text=mark, bg=BG, fg=MUTED, font=FONT, width=2).pack(side="left")
        done = tk.BooleanVar(value=bool(node.get("done")))
        tk.Checkbutton(row, variable=done, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG).pack(side="left")
        entry = tk.Entry(row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT, highlightthickness=1, highlightbackground=LINE)
        entry.insert(0, node.get("text") or "")
        entry.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        tk.Button(row, text="加分支", command=lambda node_id=node["id"]: self._add_branch(node_id), bg=PANEL, fg=FG, relief="flat", font=FONT_SMALL, padx=6).pack(side="left")
        tk.Button(row, text="去掉", command=lambda node_id=node["id"]: self._drop(node_id), bg=PANEL, fg=FG, relief="flat", font=FONT_SMALL, padx=6).pack(side="left", padx=(4, 0))
        self._editors.append({"node": node, "entry": entry, "done": done})

    def _add_flow(self) -> None:
        self.nodes = self._read()
        self.nodes.append({"id": uuid.uuid4().hex[:8], "text": "", "at": "", "done": False, "parent": ""})
        self._paint_nodes()

    def _add_branch(self, parent_id: str) -> None:
        self.nodes = self._read()
        self.nodes.append({"id": uuid.uuid4().hex[:8], "text": "", "at": "", "done": False, "parent": parent_id})
        self._paint_nodes()

    def _drop(self, node_id: str) -> None:
        rows = [row for row in self._read() if row["id"] != node_id]
        for row in rows:
            if row.get("parent") == node_id:
                row["parent"] = ""
        if not rows:
            rows = [{"id": uuid.uuid4().hex[:8], "text": "", "at": "", "done": False, "parent": ""}]
        self.nodes = rows
        self._paint_nodes()

    def _write(self) -> bool:
        plan = self._current()
        if plan is None:
            return False
        title = self.title_var.get().strip()
        if not title:
            return False
        self.app.store.set_plan_nodes(str(self.plan_id or ""), title, self._read())
        return True

    def keep(self) -> None:
        if not self.title_var.get().strip():
            tell(self.app, "便利贴", "先写任务标题。")
            return
        if not self._write():
            return
        self.on_saved()
        self.destroy()

    def _close(self) -> None:
        if self.title_var.get().strip():
            self._write()
            self.on_saved()
        self.destroy()

    def delete(self) -> None:
        self.app.store.trash_plan(str(self.plan_id or ""))
        self.on_saved()
        self.destroy()


class DraftWindow(tk.Toplevel):
    def __init__(self, app, items: list[dict], on_saved) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.on_saved = on_saved
        self.title("整理成的清单")
        self.configure(bg=BG)
        self.minsize(520, 320)
        self.transient(app)
        tk.Label(self, text="勾上要留下的，改完再加入便利贴。", bg=BG, fg=FG, font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", padx=16, pady=(14, 8))
        bar = tk.Frame(self, bg=BG)
        bar.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        ttk.Button(bar, text="加入便利贴", style="Accent.TButton", command=self.commit).pack(side="left")
        ttk.Button(bar, text="取消", style="Ghost.TButton", command=self.destroy).pack(side="right")
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        inner = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        scroll = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y", padx=(0, 12), pady=(0, 8))
        canvas.pack(side="left", fill="both", expand=True, padx=(16, 0), pady=(0, 8))
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        self.rows = []
        for item in items:
            self._row(inner, item)
        center_on(self, app, 640, 480)
        self.deiconify()
        self.grab_set()

    def _row(self, parent, item: dict) -> None:
        box = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=10, pady=8)
        box.pack(fill="x", pady=4, padx=(0, 8))
        chosen = tk.BooleanVar(value=True)
        tk.Checkbutton(box, variable=chosen, bg=CARD, fg=FG, selectcolor=PANEL, activebackground=CARD).pack(side="left")
        title = tk.StringVar(value=item.get("title") or "")
        tk.Entry(box, textvariable=title, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", font=FONT).pack(side="left", fill="x", expand=True, padx=8, ipady=3)
        horizon = tk.StringVar(value=HORIZON_LABEL.get(item.get("horizon") or "week", "本周"))
        ttk.Combobox(box, width=8, state="readonly", textvariable=horizon, values=[label for _key, label in HORIZONS]).pack(side="left")
        detail = str(item.get("detail") or "")
        if detail:
            tk.Label(parent, text=detail, bg=BG, fg=MUTED, font=FONT_SMALL, anchor="w", wraplength=560, justify="left").pack(fill="x", padx=(28, 12))
        self.rows.append({"on": chosen, "title": title, "horizon": horizon, "detail": detail, "due": item.get("due") or ""})

    def commit(self) -> None:
        picked = []
        for row in self.rows:
            if not row["on"].get():
                continue
            title = row["title"].get().strip()
            if not title:
                continue
            picked.append(
                {
                    "title": title,
                    "horizon": LABEL_HORIZON.get(row["horizon"].get(), "week"),
                    "detail": row["detail"],
                    "due": row["due"],
                    "status": "todo",
                }
            )
        if not picked:
            messagebox.showwarning("清单", "先勾选要留下的任务。", parent=self)
            return
        self.app.store.add_plans(picked)
        self.on_saved()
        self.destroy()


class PlanRemind(tk.Toplevel):
    def __init__(self, app, plans: list[dict]) -> None:
        super().__init__(app.popup_parent())
        self.withdraw()
        self.app = app
        self.title("该做的事")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.later)
        self._remind_width = 440
        self._remind_height = min(520, 168 + 58 * min(len(plans), 6))
        tk.Frame(self, bg=WARN, height=4).pack(fill="x")
        tk.Label(self, text=f"{len(plans)} 件事要处理", bg=BG, fg=FG, font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(self, text="今日、已到期，以及正在做的。", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(0, 8))
        shown = plans[:6]
        for plan in shown:
            card = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=LINE, padx=10, pady=6)
            card.pack(fill="x", padx=18, pady=3)
            status = STATUS_LABEL.get(plan.get("status") or "todo", "待做")
            scope = HORIZON_LABEL.get(plan.get("horizon") or "week", "本周")
            due = str(plan.get("due") or "")
            extra = f"    {due}" if due else ""
            tk.Label(card, text=plan.get("title") or "", bg=CARD, fg=FG, font=FONT, anchor="w").pack(fill="x")
            tk.Label(card, text=f"{scope}    {status}{extra}", bg=CARD, fg=MUTED, font=FONT_SMALL, anchor="w").pack(fill="x")
        if len(plans) > len(shown):
            tk.Label(self, text=f"还有 {len(plans) - len(shown)} 件，打开管家可以看全。", bg=BG, fg=MUTED, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(4, 0))
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=14)
        ttk.Button(bar, text="现在去看", style="Accent.TButton", command=self.open_board).pack(side="left")
        ttk.Button(bar, text="稍后提醒", style="Ghost.TButton", command=self.later).pack(side="right")
        owner = app if app.winfo_viewable() else self.master
        center_on(self, owner, self._remind_width, self._remind_height)
        self.deiconify()
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def open_board(self) -> None:
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        self.app.focus_plans()
        self.destroy()

    def later(self) -> None:
        self.destroy()


def _self_test() -> None:
    today = date(2026, 11, 10)
    sample = [
        {"id": "1", "title": "写报告", "horizon": "today", "status": "todo", "due": ""},
        {"id": "2", "title": "下周的", "horizon": "week", "status": "todo", "due": ""},
        {"id": "3", "title": "过期", "horizon": "month", "status": "todo", "due": "2026-11-01"},
        {"id": "4", "title": "在做", "horizon": "term", "status": "doing", "due": ""},
        {"id": "5", "title": "做完", "horizon": "today", "status": "done", "due": ""},
        {"id": "6", "title": "暂停", "horizon": "today", "status": "paused", "due": ""},
    ]
    titles = [item["title"] for item in due_plans(sample, today)]
    assert titles == ["过期", "写报告", "在做"], titles
    day = date.today()
    rows = [
        {"title": "还在", "horizon": "today", "status": "todo", "due": "", "trashed": False},
        {"title": "做完", "horizon": "today", "status": "done", "due": day.isoformat(), "trashed": False},
    ]
    visible = [item["title"] for item in PlanBoard._plans_on(None, rows, day)]
    assert visible == ["还在"], visible
    moved = {"title": "改期", "horizon": "week", "status": "todo", "due": "2026-11-12", "trashed": False}
    assert PlanBoard._plans_on(None, [moved], date(2026, 11, 11)) == []
    assert [item["title"] for item in PlanBoard._plans_on(None, [moved], date(2026, 11, 12))] == ["改期"]
    assert horizon_for(date(2026, 11, 12), date(2026, 11, 11)) == "week"
    assert horizon_for(date(2026, 11, 13), date(2026, 11, 11)) == "week"
    parsed = parse_plan_reply('说明\n```json\n{"tasks":[{"title":"看文献","horizon":"本周","detail":"两篇","due":""}]}\n```')
    assert parsed[0]["horizon"] == "week" and parsed[0]["title"] == "看文献"
    notes = notes_from_words("看文献、写报告", "2026-11-10")
    assert [item["title"] for item in notes] == ["看文献", "写报告"]
    assert notes_from_words("先把覆盖度看完。\n再交报告", "2026-11-10")[1]["title"] == "再交报告"
    assert week_label(date(2026, 11, 10)) == "本周    11月9日–11月15日"
    assert month_label(date(2026, 11, 10)) == "本月    2026年11月"
    presets = dict(due_presets(date(2026, 11, 10)))
    assert presets["今天"] == date(2026, 11, 10)
    assert presets["后天"] == date(2026, 11, 12)
    assert presets["一周后"] == date(2026, 11, 17)
    assert presets["下周一"] == date(2026, 11, 16)
    assert presets["两周后"] == date(2026, 11, 24)
    assert presets["本月末"] == date(2026, 11, 30)
    assert dict(due_presets(date(2026, 12, 30)))["本月末"] == date(2026, 12, 31)
    assert month_end(date(2026, 2, 5)) == date(2026, 2, 28)
    roots, children = split_nodes(
        [
            {"id": "a", "text": "先写", "parent": ""},
            {"id": "b", "text": "补一段", "parent": "a"},
        ]
    )
    assert [item["id"] for item in roots] == ["a"] and children["a"][0]["text"] == "补一段"
    edited = plan_nodes({"detail": "", "log": [{"text": "旧提纲"}, {"id": "b", "text": "改过的", "parent": "n0", "done": True}]})
    assert edited[0]["text"] == "旧提纲" and edited[1]["done"] and edited[1]["parent"] == "n0"
    try:
        parse_plan_reply('{"tasks":[]}')
    except ValueError:
        pass
    else:
        raise AssertionError("empty tasks should fail")
    import shutil
    import tempfile
    from pathlib import Path

    from store import Store

    folder = Path(tempfile.mkdtemp())
    try:
        book = Store(folder)
        plan_id = book.upsert_plan({"title": "写报告", "horizon": "week", "status": "todo", "due": "2026-11-10"})
        later = book.upsert_plan({"title": "后写的", "horizon": "today", "status": "todo", "due": "2026-11-10"})
        seqs = {item["id"]: item["seq"] for item in book.plans()}
        assert seqs[plan_id] < seqs[later]
        book.set_plan_when(plan_id, "2026-11-12", "week")
        shifted = next(item for item in book.plans() if item["id"] == plan_id)
        assert shifted["due"] == "2026-11-12" and shifted["horizon"] == "week"
        book.set_plan_nodes(plan_id, "写报告", [{"id": "a", "text": "旧提纲", "parent": ""}, {"id": "b", "text": "补一节", "parent": "a"}])
        book.set_plan_nodes(plan_id, "写报告", [{"id": "a", "text": "提纲改过", "parent": "", "done": True}])
        saved = book.plans()[0]
        assert saved["log"][0]["text"] == "提纲改过" and saved["log"][0]["done"] is True
        assert len(saved["log"]) == 1
        book.trash_plan(plan_id)
        assert book.plans()[0]["trashed"] is True
        book.restore_plan(plan_id)
        assert book.plans()[0]["trashed"] is False
        book.set_plan_view("list")
        assert book.plan_view() == "list"
        for number in range(320):
            book.upsert_plan({"title": f"批量 {number}", "horizon": "week", "status": "todo", "due": "2026-11-10"})
        titles = [item["title"] for item in book.plans()]
        assert "批量 319" in titles, "the newest note must survive the cap"
        assert "写报告" in titles, "notes still in use must survive the cap"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    print("plans self-test ok", len(titles))


if __name__ == "__main__":
    _self_test()
