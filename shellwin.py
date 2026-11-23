"""Interactive SSH shell for one account. Typed commands run on that server."""

from __future__ import annotations

import codecs
import socket
import threading
import tkinter as tk
from jobs import Job, cd_command, connect_account, explain_connect_error, lookup_workdir
from plans import center_on

FONT_NAME = "Consolas"
# Light page: directories blue, programs green, links teal, archives red. None of these are neon.
LIGHT16 = (
    "#3A403C",
    "#B85A4A",
    "#3D7A4A",
    "#8A6E28",
    "#3A6AAD",
    "#8E5A86",
    "#2A7A78",
    "#5C6560",
    "#4A5648",
    "#C4564A",
    "#2D7A45",
    "#9A7820",
    "#2F62A8",
    "#9A5088",
    "#1F7A78",
    "#243028",
)
DARK16 = (
    "#D7DDD4",
    "#E07A6A",
    "#7DCEA0",
    "#E2C16B",
    "#7EB0E8",
    "#D7A0D0",
    "#7ED0D0",
    "#C5CDC4",
    "#8A968C",
    "#FF8A7A",
    "#8EE0A8",
    "#F0D48A",
    "#8EC0F0",
    "#E8B0E0",
    "#90E0E0",
    "#F4F7F2",
)
SHELL_THEMES = {
    "mist": {"label": "柔灰", "bg": "#E7E5E0", "fg": "#3A3A38", "muted": "#6E6C68", "bold": "#2A2A28", "cursor": "#3A3A38", "colors": LIGHT16},
    "paper": {"label": "暖纸", "bg": "#F4EFE6", "fg": "#3C342C", "muted": "#7A7166", "bold": "#2C261F", "cursor": "#3C342C", "colors": LIGHT16},
    "bean": {"label": "豆沙", "bg": "#D7E4D8", "fg": "#3C463C", "muted": "#667266", "bold": "#243028", "cursor": "#3C463C", "colors": LIGHT16},
    "ink": {"label": "墨色", "bg": "#1E2420", "fg": "#D7DDD4", "muted": "#8E9A90", "bold": "#F2F6F0", "cursor": "#D7DDD4", "colors": DARK16},
}
BG = SHELL_THEMES["mist"]["bg"]
FG = SHELL_THEMES["mist"]["fg"]
MUTED = SHELL_THEMES["mist"]["muted"]
PALETTE16 = LIGHT16


def theme_palette(colors16: tuple[str, ...]) -> tuple[str, ...]:
    colors = list(colors16)
    levels = (0, 95, 135, 175, 215, 255)
    for red in levels:
        for green in levels:
            for blue in levels:
                colors.append(f"#{red:02X}{green:02X}{blue:02X}")
    for index in range(24):
        value = 8 + index * 10
        colors.append(f"#{value:02X}{value:02X}{value:02X}")
    return tuple(colors)


PALETTE = theme_palette(LIGHT16)


class Screen:
    """Visible terminal page plus scrollback. Cursor motion follows the server."""

    def __init__(self, rows: int = 32, cols: int = 100) -> None:
        self.rows = rows
        self.cols = cols
        self.scrollback: list[list[tuple[str, int, int, bool]]] = []
        self.grid = [self._blank_line() for _ in range(rows)]
        self.row = 0
        self.col = 0
        self.fg = -1
        self.bg = -1
        self.bold = False
        self._esc = ""
        self._mode = ""
        self.rev = 0

    def _blank(self) -> tuple[str, int, int, bool]:
        return (" ", -1, -1, False)

    def _blank_line(self) -> list[tuple[str, int, int, bool]]:
        return [self._blank() for _ in range(self.cols)]

    def resize(self, rows: int, cols: int) -> None:
        rows = max(8, int(rows))
        cols = max(20, int(cols))
        if rows == self.rows and cols == self.cols:
            return
        grid = self.grid
        if rows < len(grid):
            drop = min(len(grid) - rows, self.row)
            for line in grid[:drop]:
                self.scrollback.append(line)
            grid = grid[drop:]
            self.row -= drop
            grid = grid[:rows]
        while len(grid) < rows:
            grid.append([self._blank() for _ in range(self.cols)])
        fitted = []
        for line in grid:
            if len(line) < cols:
                line = line + [self._blank() for _ in range(cols - len(line))]
            else:
                line = line[:cols]
            fitted.append(line)
        self.grid = fitted
        self.rows = rows
        self.cols = cols
        self.row = min(self.row, rows - 1)
        self.col = min(self.col, cols - 1)
        if len(self.scrollback) > 3000:
            del self.scrollback[:-3000]
        self.rev += 1

    def feed(self, text: str) -> None:
        self.rev += 1
        for char in text:
            if self._esc:
                self._take_escape(char)
                continue
            if char == "\x1b":
                self._esc = char
                self._mode = ""
                continue
            if char == "\r":
                self.col = 0
                continue
            if char == "\n":
                self._newline()
                continue
            if char in {"\b", "\x7f"}:
                self.col = max(0, self.col - 1)
                continue
            if char == "\t":
                pad = 4 - (self.col % 4)
                for _ in range(pad):
                    self._put(" ")
                continue
            if char >= " ":
                self._put(char)

    def _take_escape(self, char: str) -> None:
        if char == "\x1b" and self._mode != "osc":
            self._esc = "\x1b"
            self._mode = ""
            return
        self._esc += char
        if len(self._esc) == 2 and char == "]":
            self._mode = "osc"
            return
        if len(self._esc) == 2 and char != "[":
            self._esc = ""
            self._mode = ""
            return
        if self._mode == "osc":
            if char == "\x07" or self._esc.endswith("\x1b\\") or len(self._esc) > 256:
                self._esc = ""
                self._mode = ""
            return
        if len(self._esc) >= 3 and "\x40" <= char <= "\x7e":
            self._apply_escape(self._esc)
            self._esc = ""
            self._mode = ""
        elif len(self._esc) > 64:
            self._esc = ""
            self._mode = ""

    def _newline(self) -> None:
        if self.row >= self.rows - 1:
            self.scrollback.append(self.grid.pop(0))
            self.grid.append(self._blank_line())
            if len(self.scrollback) > 3000:
                del self.scrollback[:-3000]
        else:
            self.row += 1
        self.col = 0

    def _apply_escape(self, seq: str) -> None:
        if not seq.startswith("\x1b[") or len(seq) < 3:
            return
        final = seq[-1]
        body = seq[2:-1]
        if body[:1] in {"?", ">"}:
            return
        numbers = []
        for part in body.split(";") if body else []:
            numbers.append(int(part) if part.isdigit() else 0)

        def count(index: int, default: int) -> int:
            if index < len(numbers) and numbers[index] > 0:
                return numbers[index]
            return default

        if final == "m":
            self._sgr(numbers or [0])
        elif final == "A":
            self.row = max(0, self.row - count(0, 1))
        elif final == "B":
            self.row = min(self.rows - 1, self.row + count(0, 1))
        elif final == "C":
            self.col = min(self.cols - 1, self.col + count(0, 1))
        elif final == "D":
            self.col = max(0, self.col - count(0, 1))
        elif final == "G":
            self.col = min(self.cols - 1, count(0, 1) - 1)
        elif final in {"H", "f"}:
            self.row = min(self.rows - 1, count(0, 1) - 1)
            self.col = min(self.cols - 1, count(1, 1) - 1)
        elif final == "K":
            self._erase_line(numbers[0] if numbers else 0)
        elif final == "J":
            self._erase_display(numbers[0] if numbers else 0)
        elif final == "P":
            self._delete_chars(count(0, 1))
        elif final == "X":
            self._erase_chars(count(0, 1))

    def _sgr(self, numbers: list[int]) -> None:
        index = 0
        while index < len(numbers):
            code = numbers[index]
            if code == 0:
                self.fg = -1
                self.bg = -1
                self.bold = False
            elif code == 1:
                self.bold = True
            elif code == 22:
                self.bold = False
            elif 30 <= code <= 37:
                self.fg = code - 30
            elif code == 39:
                self.fg = -1
            elif 40 <= code <= 47:
                self.bg = code - 40
            elif code == 49:
                self.bg = -1
            elif 90 <= code <= 97:
                self.fg = code - 90 + 8
            elif 100 <= code <= 107:
                self.bg = code - 100 + 8
            elif code in {38, 48} and index + 2 < len(numbers) and numbers[index + 1] == 5:
                value = max(0, min(255, numbers[index + 2]))
                if code == 38:
                    self.fg = value
                else:
                    self.bg = value
                index += 2
            elif code in {38, 48} and index + 4 < len(numbers) and numbers[index + 1] == 2:
                index += 4
            index += 1

    def _erase_line(self, mode: int) -> None:
        line = self.grid[self.row]
        if mode == 1:
            start, end = 0, min(self.cols, self.col + 1)
        elif mode == 2:
            start, end = 0, self.cols
        else:
            start, end = self.col, self.cols
        blank = self._blank()
        for pos in range(start, end):
            line[pos] = blank

    def _erase_display(self, mode: int) -> None:
        if mode in {2, 3}:
            self.grid = [self._blank_line() for _ in range(self.rows)]
            self.row = 0
            self.col = 0
            return
        if mode == 1:
            for index in range(self.row):
                self.grid[index] = self._blank_line()
            self._erase_line(1)
            return
        self._erase_line(0)
        for index in range(self.row + 1, self.rows):
            self.grid[index] = self._blank_line()

    def _delete_chars(self, count: int) -> None:
        line = self.grid[self.row]
        del line[self.col : self.col + count]
        while len(line) < self.cols:
            line.append(self._blank())

    def _erase_chars(self, count: int) -> None:
        line = self.grid[self.row]
        blank = self._blank()
        for pos in range(self.col, min(self.cols, self.col + count)):
            line[pos] = blank

    def _put(self, char: str) -> None:
        if self.col >= self.cols:
            self._newline()
        self.grid[self.row][self.col] = (char, self.fg, self.bg, self.bold)
        self.col += 1

    def snapshot(self, limit: int | None = None) -> tuple[list[list[tuple[str, int, int, bool]]], int, int]:
        last = self.row
        for index, line in enumerate(self.grid):
            if index <= self.row:
                continue
            if any(cell[0] != " " or cell[1] != -1 or cell[2] != -1 for cell in line):
                last = index
        lines = list(self.scrollback) + self.grid[: last + 1]
        cursor = len(self.scrollback) + self.row
        if limit and len(lines) > limit:
            cut = len(lines) - limit
            lines = lines[cut:]
            cursor -= cut
        return lines, cursor, self.col

    def text(self) -> str:
        lines, _row, _col = self.snapshot()
        out = []
        for line in lines:
            out.append("".join(cell[0] for cell in line).rstrip())
        while out and out[-1] == "":
            out.pop()
        return "\n".join(out)


class ShellWindow(tk.Toplevel):
    def __init__(self, app, job: Job, account: dict, password: str) -> None:
        super().__init__(app)
        self.withdraw()
        self.app = app
        self.job = job
        self.account = account
        self._password = password
        self.client = None
        self.channel = None
        self.alive = True
        self.screen = Screen()
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.font_size = 12
        self._tags: set[str] = set()
        self._resize_job = None
        self._pending: list[str] = []
        self._paint_job = None
        self._dragging = False
        # Repainting thousands of lines on every chunk froze the window. Repaint only
        # when the screen actually changed, and only the tail that can be reached.
        self.render_limit = 1200
        self._render_key = None
        who = f"{account.get('username')}@{account.get('host')}:{account.get('port')}"
        if (job.job_id or "").strip():
            self.title(f"命令行  {job.job_id}  {job.name or ''}".strip())
        else:
            label = (account.get("label") or "").strip() or (account.get("username") or "")
            self.title(f"命令行  {label}".strip())
        self.theme_name = "mist"
        self.colors = PALETTE
        self.bold_fg = FG
        spec = SHELL_THEMES["mist"]
        self.configure(bg=spec["bg"])
        self.minsize(640, 420)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.who_label = tk.Label(self, text=who, bg=spec["bg"], fg=spec["fg"], font=("Microsoft YaHei UI", 12, "bold"))
        self.who_label.pack(anchor="w", padx=12, pady=(10, 0))
        self.status = tk.StringVar(value="正在登录…")
        self.status_label = tk.Label(self, textvariable=self.status, bg=spec["bg"], fg=spec["muted"], font=("Microsoft YaHei UI", 9))
        self.status_label.pack(anchor="w", padx=12, pady=(2, 6))
        self.box = tk.Text(
            self,
            bg=spec["bg"],
            fg=spec["fg"],
            insertbackground=spec["cursor"],
            insertofftime=0,
            insertwidth=2,
            relief="flat",
            font=(FONT_NAME, self.font_size),
            wrap="none",
            padx=12,
            pady=8,
            undo=False,
        )
        self.box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.box.bind("<Key>", self.on_key)
        self.box.bind("<<Paste>>", self.on_paste)
        self.box.bind("<ButtonPress-1>", self._on_press)
        self.box.bind("<ButtonRelease-1>", self._on_release)
        self.box.bind("<Button-3>", self._paste_clipboard)
        self.box.bind("<Control-Insert>", self._copy_selection)
        self.box.bind("<Shift-Insert>", self._paste_clipboard)
        self.box.bind("<Control-MouseWheel>", self._zoom)
        self.bind("<Control-MouseWheel>", self._zoom)
        self.box.bind("<MouseWheel>", self._wheel)
        self.box.bind("<Configure>", self._schedule_resize)
        self.bar = tk.Frame(self, bg=spec["bg"])
        self.bar.pack(fill="x", padx=12, pady=(0, 10))
        self.theme_btn = tk.Button(self.bar, text="配色", command=self._open_themes, relief="flat", bd=0, padx=10, pady=2, font=("Microsoft YaHei UI", 9))
        self.theme_btn.pack(side="left")
        self.close_btn = tk.Button(self.bar, text="关闭", command=self.close, relief="flat", bd=0, padx=10, pady=2, font=("Microsoft YaHei UI", 9))
        self.close_btn.pack(side="right")
        self.use_theme(self.app.store.shell_theme(), save=False)
        self._write_local(self._banner(who))
        center_on(self, app, 860, 560)
        self.deiconify()
        self.box.focus_set()
        threading.Thread(target=self._connect, daemon=True).start()

    def use_theme(self, name: str, save: bool = True) -> None:
        spec = SHELL_THEMES.get(name) or SHELL_THEMES["mist"]
        self.theme_name = name if name in SHELL_THEMES else "mist"
        self.colors = theme_palette(spec["colors"])
        self.bold_fg = spec["bold"]
        bg, fg, muted = spec["bg"], spec["fg"], spec["muted"]
        self.configure(bg=bg)
        self.who_label.configure(bg=bg, fg=fg)
        self.status_label.configure(bg=bg, fg=muted)
        self.bar.configure(bg=bg)
        for button in (self.theme_btn, self.close_btn):
            button.configure(bg=bg, fg=fg, activebackground=fg, activeforeground=bg)
        self.box.configure(bg=bg, fg=fg, insertbackground=spec["cursor"], insertofftime=0, insertwidth=2)
        for tag in list(self._tags):
            try:
                self.box.tag_delete(tag)
            except tk.TclError:
                pass
        self._tags.clear()
        if save:
            self.app.store.set_shell_theme(self.theme_name)
        self._render_key = None
        self._render()

    def _open_themes(self) -> None:
        spec = SHELL_THEMES[self.theme_name]
        menu = tk.Menu(self, tearoff=0, bg=spec["bg"], fg=spec["fg"], activebackground=spec["fg"], activeforeground=spec["bg"], font=("Microsoft YaHei UI", 10))
        for key, item in SHELL_THEMES.items():
            mark = "    当前" if key == self.theme_name else ""
            menu.add_command(label=item["label"] + mark, command=lambda chosen=key: self.use_theme(chosen))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def _banner(self, who: str) -> str:
        where = self.job.workdir or "家目录"
        lines = [f"正在登录 {who}"]
        if (self.job.job_id or "").strip():
            lines.append(f"作业 {self.job.job_id}  {self.job.name or '未命名'}")
        else:
            lines.append("从账号进入，停在家目录。")
        lines.append(f"目录 {where}")
        lines.append("这是该账号的命令行。你输入的命令会在这台机器上执行。")
        lines.append("按住 Ctrl，滚动鼠标滚轮可以放大或缩小字体。左下角「配色」可以换背景。")
        lines.append("鼠标选中文字会自动复制，右键或 Shift+Insert 粘贴。")
        lines.append("")
        return "\n".join(lines)

    def _wheel(self, event):
        if event.state & 0x4:
            return self._zoom(event)

    def _zoom(self, event) -> str:
        step = 1 if event.delta > 0 else -1
        size = min(28, max(8, self.font_size + step))
        if size != self.font_size:
            self.font_size = size
            self.box.configure(font=(FONT_NAME, size))
            self._schedule_resize()
        return "break"

    def _schedule_resize(self, _event=None) -> None:
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(120, self._apply_resize)

    def _apply_resize(self) -> None:
        self._resize_job = None
        if not self.winfo_exists():
            return
        try:
            char_w = max(1, int(self.box.tk.call("font", "measure", self.box.cget("font"), "M")))
            char_h = max(1, int(self.box.tk.call("font", "metrics", self.box.cget("font"), "-linespace")))
        except tk.TclError:
            return
        cols = max(40, (self.box.winfo_width() - 24) // char_w)
        rows = max(12, (self.box.winfo_height() - 16) // char_h)
        self.screen.resize(rows, cols)
        self.box.configure(insertwidth=2, insertofftime=0)
        channel = self.channel
        if channel is not None:
            try:
                channel.resize_pty(width=cols, height=rows)
            except Exception:
                pass
        self._render()

    def _write_local(self, text: str) -> None:
        self.screen.feed(text)
        self._render()

    def _render(self) -> None:
        if not self.winfo_exists():
            return
        key = (self.screen.rev, self.screen.row, self.screen.col, self.render_limit)
        if key == self._render_key:
            return
        self._render_key = key
        lines, cursor_line, cursor_col = self.screen.snapshot(self.render_limit)
        self.box.delete("1.0", "end")
        for index, line in enumerate(lines):
            if index:
                self.box.insert("end", "\n")
            end = len(line)
            while end > 0 and line[end - 1][0] == " " and line[end - 1][1] < 0 and line[end - 1][2] < 0:
                end -= 1
            if index == cursor_line:
                end = max(end, min(cursor_col, len(line)))
            self._insert_run(line[:end])
        row = max(1, cursor_line + 1)
        self.box.mark_set("insert", f"{row}.{max(0, cursor_col)}")
        self.box.see("insert")

    def _insert_run(self, line: list[tuple[str, int, int, bool]]) -> None:
        run = ""
        style = None
        for char, fg, bg, bold in line:
            current = (fg, bg, bold)
            if style is None:
                style = current
                run = char
                continue
            if current != style:
                self.box.insert("end", run, self._style(style))
                style = current
                run = char
            else:
                run += char
        if run:
            self.box.insert("end", run, self._style(style or (-1, -1, False)))

    def _style(self, style: tuple[int, int, bool]) -> str:
        fg, bg, bold = style
        shown = fg
        if bold and 0 <= fg < 8:
            shown = fg + 8
        name = f"c{shown}_{bg}_{int(bold)}"
        if name not in self._tags:
            options = {}
            if shown >= 0:
                options["foreground"] = self.colors[min(shown, len(self.colors) - 1)]
            elif bold:
                options["foreground"] = self.bold_fg
            if bg >= 0:
                options["background"] = self.colors[min(bg, len(self.colors) - 1)]
            self.box.tag_configure(name, **options)
            self._tags.add(name)
        return name

    def _incoming(self, text: str) -> None:
        self._pending.append(text)
        if self._paint_job is None:
            self._paint_job = self.after(50, self._flush_incoming)

    def _flush_incoming(self) -> None:
        self._paint_job = None
        if not self._pending or not self.winfo_exists():
            self._pending.clear()
            return
        if self._dragging:
            # Repainting wipes the selection; only wait while the mouse is still down.
            self._paint_job = self.after(80, self._flush_incoming)
            return
        chunk = "".join(self._pending)
        self._pending.clear()
        self.screen.feed(chunk)
        self._render()

    def _set_status(self, text: str) -> None:
        if self.winfo_exists():
            self.status.set(text)

    def _connect(self) -> None:
        password = self._password
        self._password = ""
        try:
            client = connect_account(self.account, password, self.app.store.known_hosts_path())
            if not self.alive:
                client.close()
                return
            workdir = (self.job.workdir or "").strip()
            if not workdir and (self.job.job_id or "").strip():
                workdir = lookup_workdir(client, self.job.job_id)
                if workdir:
                    self.job.workdir = workdir
            channel = client.invoke_shell(term="xterm-256color", width=self.screen.cols, height=self.screen.rows)
            channel.settimeout(0.2)
            command = cd_command(workdir)
            if command:
                channel.send(command.encode("utf-8"))
            self.client = client
            self.channel = channel
            place = workdir or "家目录"
            self.after(0, lambda: self._set_status(f"已登录    目录 {place}"))
            self._read(channel)
        except Exception as exc:
            message = explain_connect_error(exc)
            self.after(0, lambda: self._fail(message))

    def _fail(self, message: str) -> None:
        self._set_status(message)
        self._write_local("\n" + message + "\n")

    def _read(self, channel) -> None:
        while self.alive:
            try:
                data = channel.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            if not data:
                break
            text = self.decoder.decode(data)
            if text:
                self.after(0, lambda chunk=text: self._incoming(chunk))
        self.after(0, lambda: self._set_status("连接已结束"))

    def _send(self, data: str) -> None:
        channel = self.channel
        if channel is None:
            return
        try:
            channel.send(data.encode("utf-8"))
        except Exception:
            self._set_status("发送失败，连接可能已经断开。")

    def on_key(self, event) -> str:
        control = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        key = event.keysym
        if control and shift and key.lower() == "c":
            try:
                text = self.box.get("sel.first", "sel.last")
            except tk.TclError:
                return "break"
            self.clipboard_clear()
            self.clipboard_append(text)
            return "break"
        if control and key.lower() == "v":
            self.on_paste(event)
            return "break"
        if control and key.lower() == "c":
            self._send("\x03")
            return "break"
        if control and key.lower() == "d":
            self._send("\x04")
            return "break"
        arrows = {"Up": "\x1b[A", "Down": "\x1b[B", "Right": "\x1b[C", "Left": "\x1b[D"}
        if key in arrows:
            if control:
                moved = {"Left": "\x1b[1;5D", "Right": "\x1b[1;5C", "Up": "\x1b[1;5A", "Down": "\x1b[1;5B"}
                self._send(moved[key])
            else:
                self._send(arrows[key])
        elif key == "Return":
            self._send("\r")
        elif key == "BackSpace":
            self._send("\x7f")
        elif key == "Delete":
            self._send("\x1b[3~")
        elif key == "Home":
            self._send("\x1b[H")
        elif key == "End":
            self._send("\x1b[F")
        elif key == "Tab":
            self._send("\t")
        elif key == "Escape":
            self._send("\x1b")
        elif event.char and event.char >= " " and not control:
            self._send(event.char)
        return "break"

    def on_paste(self, _event=None) -> str:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return "break"
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r")
        if len(text) > 8000:
            self._write_local(f"\n[粘贴内容太长，只发送了前 8000 个字符，剩下 {len(text) - 8000} 个没有发送]\n")
        if text:
            self._send(text[:8000])
        return "break"

    def _on_press(self, _event=None) -> None:
        self._dragging = True

    def _on_release(self, _event=None) -> None:
        self._dragging = False
        self._auto_copy()
        if self._pending and self._paint_job is None:
            self._paint_job = self.after(10, self._flush_incoming)

    def _auto_copy(self, _event=None) -> None:
        """MobaXterm style: releasing the mouse over a selection copies it."""
        try:
            text = self.box.get("sel.first", "sel.last")
        except tk.TclError:
            return
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        try:
            self.update_idletasks()
        except tk.TclError:
            pass

    def _copy_selection(self, _event=None) -> str:
        self._auto_copy()
        return "break"

    def _paste_clipboard(self, _event=None) -> str:
        try:
            self.box.tag_remove("sel", "1.0", "end")
        except tk.TclError:
            pass
        self.on_paste()
        return "break"

    def close(self) -> None:
        self.alive = False
        channel = self.channel
        client = self.client
        self.channel = None
        self.client = None
        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        self.destroy()


def _self_test() -> None:
    screen = Screen()
    screen.feed("hello\r\n")
    screen.feed("abc\b\bX")
    screen.feed("\x1b[1;34mdir\x1b[0m \x1b[31mzip\x1b[0m")
    assert "hello" in screen.text() and "dir" in screen.text() and "zip" in screen.text()
    flat = [cell for line in screen.grid for cell in line]
    directory = next(cell for cell in flat if cell[0] == "d")
    archive = next(cell for cell in flat if cell[0] == "z")
    assert directory[1] == 4 and directory[3]
    assert archive[1] == 1 and not archive[3]
    assert "\x1b" not in screen.text()
    edited = Screen()
    edited.feed("ab\b \b")
    assert edited.text() == "a"
    edited.feed("\x1b[Cyz\x1b[2D\x1b[K")
    assert edited.text() == "a"
    edited.feed("\x1b[D")
    assert edited.col == 1
    edited.feed("\x1b[D\x1b[D")
    assert edited.col == 0
    assert SHELL_THEMES["mist"]["bg"] == "#E7E5E0" and SHELL_THEMES["bean"]["bg"] != "#000000"
    assert SHELL_THEMES["ink"]["bg"] != "#000000"
    assert LIGHT16[12] == "#2F62A8" and LIGHT16[10] == "#2D7A45" and LIGHT16[9] == "#C4564A"
    assert DARK16[12] == "#8EC0F0"
    print("shell self-test ok")


if __name__ == "__main__":
    _self_test()
