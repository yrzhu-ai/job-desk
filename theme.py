"""Skin colors and rounded panels."""

from __future__ import annotations

import tkinter as tk

try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:
    Image = None
    ImageDraw = None
    ImageTk = None

SKINS = {
    "night": {
        "label": "深夜",
        "bg": "#10141c",
        "panel": "#1a2130",
        "card": "#222b3c",
        "fg": "#f3f6fb",
        "muted": "#8b98ad",
        "accent": "#6c8cff",
        "line": "#313c52",
        "ok": "#3dce8f",
        "warn": "#f2b544",
        "bad": "#ff6d7d",
        "heading": "#2a384c",
        "on_accent": "#ffffff",
        "sash": "#4d6494",
        "run_bg": "#17372c",
        "run_fg": "#d9ffe9",
        "wait_bg": "#2c2616",
        "wait_fg": "#ffe7ad",
        "done_bg": "#15261e",
        "done_fg": "#c9ddd4",
        "bad_bg": "#2a171c",
        "bad_fg": "#ffd5dc",
        "pick": "#3559b5",
    },
    "sea": {
        "label": "海洋",
        "bg": "#0e1c24",
        "panel": "#16303a",
        "card": "#1c3b46",
        "fg": "#e7f6f8",
        "muted": "#8eb4bf",
        "accent": "#2aa7b8",
        "line": "#2d5562",
        "ok": "#3dce8f",
        "warn": "#f2b544",
        "bad": "#ff6d7d",
        "heading": "#1f4d5c",
        "on_accent": "#ffffff",
        "sash": "#2f8b99",
        "run_bg": "#12352e",
        "run_fg": "#d7f6ea",
        "wait_bg": "#3a3218",
        "wait_fg": "#ffe7ad",
        "done_bg": "#102830",
        "done_fg": "#c5dde4",
        "bad_bg": "#3a1c24",
        "bad_fg": "#ffd0d6",
        "pick": "#1f7d8c",
    },
    "paper": {
        "label": "纸页",
        "bg": "#efe8db",
        "panel": "#f7f1e6",
        "card": "#fbf6ee",
        "fg": "#3a332b",
        "muted": "#756c62",
        "accent": "#7d5a3a",
        "line": "#d9cdb8",
        "ok": "#2f7d55",
        "warn": "#9a6b12",
        "bad": "#b44a4a",
        "heading": "#e4d8c4",
        "on_accent": "#fffaf3",
        "sash": "#cfc0aa",
        "run_bg": "#e3f0e4",
        "run_fg": "#24543a",
        "wait_bg": "#f6edd4",
        "wait_fg": "#6b5014",
        "done_bg": "#f3eee6",
        "done_fg": "#6e655c",
        "bad_bg": "#f6e4e1",
        "bad_fg": "#8d3b3b",
        "pick": "#7d5a3a",
    },
    "leaf": {
        "label": "新绿",
        "bg": "#121a14",
        "panel": "#1b2a20",
        "card": "#243528",
        "fg": "#eef6ef",
        "muted": "#93aa98",
        "accent": "#6fbf73",
        "line": "#355040",
        "ok": "#8ed18a",
        "warn": "#e2c16b",
        "bad": "#e07a7a",
        "heading": "#2c4034",
        "on_accent": "#102033",
        "sash": "#5d9a61",
        "run_bg": "#1a3324",
        "run_fg": "#dff6e4",
        "wait_bg": "#3a341c",
        "wait_fg": "#f3e2b0",
        "done_bg": "#1a2820",
        "done_fg": "#c9ddd0",
        "bad_bg": "#3a2224",
        "bad_fg": "#f6d0d0",
        "pick": "#3d7a45",
    },
    "ember": {
        "label": "落日",
        "bg": "#1a1210",
        "panel": "#241a16",
        "card": "#2e211b",
        "fg": "#fbf1e6",
        "muted": "#b39a86",
        "accent": "#e8843c",
        "line": "#453026",
        "ok": "#7fc98a",
        "warn": "#f0b24a",
        "bad": "#ef6f5c",
        "heading": "#3a2820",
        "on_accent": "#1a1210",
        "sash": "#7a4a2a",
        "run_bg": "#1f2f22",
        "run_fg": "#cfe9cf",
        "wait_bg": "#33261a",
        "wait_fg": "#f3d7a6",
        "done_bg": "#1e2622",
        "done_fg": "#cbd8cf",
        "bad_bg": "#33191a",
        "bad_fg": "#f6c7c2",
        "pick": "#8a4a24",
    },
    "light": {
        "label": "极简",
        "bg": "#f4f6f9",
        "panel": "#ffffff",
        "card": "#fafbfd",
        "fg": "#1f2733",
        "muted": "#6b7785",
        "accent": "#2563c9",
        "line": "#dfe5ec",
        "ok": "#1f7a4d",
        "warn": "#9a6b12",
        "bad": "#b53b3b",
        "heading": "#e8edf3",
        "on_accent": "#ffffff",
        "sash": "#c9d2dc",
        "run_bg": "#e6f4ea",
        "run_fg": "#1d5c37",
        "wait_bg": "#fdf1d6",
        "wait_fg": "#7a5a12",
        "done_bg": "#f2f4f7",
        "done_fg": "#5d6773",
        "bad_bg": "#fbe9e9",
        "bad_fg": "#8f3232",
        "pick": "#1b4fa0",
    },
    "sakura": {
        "label": "樱花",
        "bg": "#fdf3f6",
        "panel": "#fffafc",
        "card": "#fffdfe",
        "fg": "#3a2730",
        "muted": "#8b6f7a",
        "accent": "#d4507a",
        "line": "#f0d7e0",
        "ok": "#3f8f6a",
        "warn": "#a77420",
        "bad": "#c2415a",
        "heading": "#f7dfe8",
        "on_accent": "#ffffff",
        "sash": "#e7b9c9",
        "run_bg": "#e9f5ee",
        "run_fg": "#2c6349",
        "wait_bg": "#fbeed6",
        "wait_fg": "#7d5a18",
        "done_bg": "#f7edf1",
        "done_fg": "#6d5962",
        "bad_bg": "#fbe2e7",
        "bad_fg": "#8e2f45",
        "pick": "#b03a62",
    },
    "contrast": {
        "label": "高对比",
        "bg": "#000000",
        "panel": "#0d0d0d",
        "card": "#161616",
        "fg": "#f5f5f5",
        "muted": "#b8b8b8",
        "accent": "#ffd400",
        "line": "#3a3a3a",
        "ok": "#33d17a",
        "warn": "#ffb000",
        "bad": "#ff5b5b",
        "heading": "#262626",
        "on_accent": "#000000",
        "sash": "#ffd400",
        "run_bg": "#0f2a18",
        "run_fg": "#7dffb0",
        "wait_bg": "#2e2400",
        "wait_fg": "#ffe680",
        "done_bg": "#141414",
        "done_fg": "#d0d0d0",
        "bad_bg": "#2c0d0d",
        "bad_fg": "#ffb3b3",
        "pick": "#ffd400",
    },
}

BG_ROLES = ("bg", "panel", "card", "accent", "line", "heading", "sash", "pick")
FG_ROLES = ("fg", "muted", "accent", "ok", "warn", "bad", "on_accent")


class Palette:
    def __init__(self) -> None:
        self.use("night")

    def use(self, name: str) -> None:
        spec = SKINS.get(name) or SKINS["night"]
        self.name = name if name in SKINS else "night"
        self.label = spec["label"]
        for key, value in spec.items():
            if key != "label":
                setattr(self, key, value)


palette = Palette()
_PHOTOS: dict[tuple, tk.PhotoImage] = {}


def sync_modules() -> None:
    """Push the active palette into the modules that own the colour constants.

    The packed exe runs app.py as ``__main__``; importing "app" there would update
    a *second* copy of the module and leave the running one on the old skin.
    """
    import sys

    values = {
        "BG": palette.bg,
        "PANEL": palette.panel,
        "CARD": palette.card,
        "FG": palette.fg,
        "MUTED": palette.muted,
        "ACCENT": palette.accent,
        "OK": palette.ok,
        "WARN": palette.warn,
        "BAD": palette.bad,
        "LINE": palette.line,
        "HEADING": palette.heading,
    }
    seen = set()
    for name in ("__main__", "app", "plans"):
        module = sys.modules.get(name)
        if module is None or id(module) in seen:
            continue
        seen.add(id(module))
        for key, value in values.items():
            if hasattr(module, key):
                setattr(module, key, value)


def _role_maps() -> tuple[dict[str, str], dict[str, str]]:
    backgrounds: dict[str, str] = {}
    foregrounds: dict[str, str] = {}
    for spec in SKINS.values():
        for role in BG_ROLES:
            backgrounds[spec[role].lower()] = role
        for role in FG_ROLES:
            foregrounds[spec[role].lower()] = role
    return backgrounds, foregrounds


def _luma(color: str) -> float:
    text = str(color or "").strip().lstrip("#")
    if len(text) != 6:
        return 0.0
    try:
        red, green, blue = (int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError:
        return 0.0
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def is_light() -> bool:
    """True for the light skins, so sticky notes and badges can flip with them."""
    return _luma(palette.bg) > 0.55


def readable_on(background: str) -> str:
    """Pick dark or light ink for a given background."""
    return "#101010" if _luma(background) > 0.6 else "#ffffff"


def clear_photos() -> None:
    _PHOTOS.clear()


def rounded_photo(width: int, height: int, fill: str, radius: int = 18, outline: str = "") -> tk.PhotoImage | None:
    width = max(2, int(width))
    height = max(2, int(height))
    radius = max(0, min(int(radius), width // 2, height // 2))
    key = (width, height, fill, radius, outline)
    cached = _PHOTOS.get(key)
    if cached is not None:
        return cached
    if Image is None or ImageDraw is None or ImageTk is None:
        return None
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=radius, fill=fill, outline=outline or fill, width=1)
    photo = ImageTk.PhotoImage(image)
    if len(_PHOTOS) > 80:
        _PHOTOS.clear()
    _PHOTOS[key] = photo
    return photo


TEXT_CHOICES = (
    ("Microsoft YaHei UI", "微软雅黑"),
    ("SimSun", "宋体"),
    ("SimHei", "黑体"),
    ("KaiTi", "楷体"),
)
TEXT_SIZES = (
    (9, "小"),
    (10, "标准"),
    (12, "大"),
    (14, "特大"),
    (16, "更大"),
)
_MONO = {"consolas", "courier", "courier new", "cascadia mono"}


class TextLook:
    def __init__(self) -> None:
        self.family = "Microsoft YaHei UI"
        self.size = 10


text_look = TextLook()


def parse_font(value) -> tuple[str, int, str]:
    if isinstance(value, (tuple, list)):
        family = str(value[0]) if value else ""
        size = int(value[1]) if len(value) > 1 else 10
        weight = str(value[2]) if len(value) > 2 else ""
        return family, size, weight
    text = str(value).strip()
    weight = ""
    if text.startswith("{") and "}" in text:
        family = text[1 : text.find("}")]
        rest = text[text.find("}") + 1 :].split()
    else:
        parts = text.split()
        if parts and parts[-1] in {"bold", "italic", "normal"}:
            weight = parts.pop()
        size_text = parts.pop() if parts else "10"
        try:
            size = int(float(size_text))
        except ValueError:
            size = 10
            parts.append(size_text)
        return " ".join(parts), size, weight
    try:
        size = int(float(rest[0])) if rest else 10
    except ValueError:
        size = 10
    if len(rest) > 1:
        weight = rest[1]
    return family, size, weight


def apply_text(widget, family: str, size: int) -> None:
    """Resize existing text from the last chosen size, and switch the font."""
    size = max(9, min(18, int(size)))
    old = text_look.size or size
    allowed = {item[0] for item in TEXT_CHOICES}
    if family not in allowed:
        family = "Microsoft YaHei UI"

    def walk(node) -> None:
        raw = None
        try:
            raw = node.cget("font")
        except tk.TclError:
            raw = None
        if raw:
            current, current_size, weight = parse_font(raw)
            if current.lower() not in _MONO:
                scaled = max(8, int(round(current_size * size / old)))
                spec = (family, scaled, weight) if weight and weight != "normal" else (family, scaled)
                try:
                    node.configure(font=spec)
                except tk.TclError:
                    pass
        for child in list(node.winfo_children()):
            walk(child)

    walk(widget)
    text_look.family = family
    text_look.size = size


def round_window(window, radius: int = 28) -> None:
    """Soften a window's outer corners without covering the close button."""
    if getattr(window, "_round_ready", False):
        window._round_radius = radius
        return
    window._round_ready = True
    window._round_radius = radius
    window._round_size = (0, 0)
    window._round_job = None

    def apply() -> None:
        window._round_job = None
        try:
            if not window.winfo_exists():
                return
            import ctypes

            if str(window.state()) == "zoomed":
                hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
                ctypes.windll.user32.SetWindowRgn(hwnd, 0, True)
                window._round_size = (0, 0)
                return
            width = int(window.winfo_width())
            height = int(window.winfo_height())
            if width < 80 or height < 80 or (width, height) == window._round_size:
                return
            window._round_size = (width, height)
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
            curve = max(16, min(36, int(window._round_radius)))
            region = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, curve, curve)
            ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
        except Exception:
            pass

    def schedule(event=None) -> None:
        if event is not None and event.widget is not window:
            return
        job = window._round_job
        if job:
            try:
                window.after_cancel(job)
            except tk.TclError:
                pass
        window._round_job = window.after(80, apply)

    window.bind("<Configure>", schedule, add="+")
    window.after(40, apply)


class RoundCard(tk.Frame):
    """A panel with rounded corners. Put widgets in `.body`."""

    def __init__(self, master, fill: str, radius: int = 28, pad: int = 16, outline: str = "", parent_bg: str = "", fill_role: str = "card", parent_role: str = "bg") -> None:
        if not parent_bg:
            try:
                parent_bg = str(master.cget("bg"))
            except tk.TclError:
                parent_bg = palette.bg
        super().__init__(master, bg=parent_bg, highlightthickness=0, bd=0)
        self._fill = fill
        self._outline = outline or fill
        self._radius = radius
        self._pad = pad
        self._parent_bg = parent_bg
        self._fill_role = fill_role
        self._parent_role = parent_role
        self._photo = None
        self._size = (0, 0)
        self._paint_job = None
        self.skin = tk.Canvas(self, width=8, height=8, highlightthickness=0, bd=0, bg=parent_bg)
        self.skin.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._image_id = None
        self.body = tk.Frame(self, bg=fill, highlightthickness=0, bd=0)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, event) -> None:
        if event.widget is not self:
            return
        if self._paint_job is not None:
            return
        self._paint_job = self.after_idle(self._paint)

    def _paint(self) -> None:
        self._paint_job = None
        if not self.winfo_exists():
            return
        width = int(self.winfo_width())
        height = int(self.winfo_height())
        if width < 8 or height < 8:
            return
        if (width, height) == self._size and self._photo is not None:
            return
        self._size = (width, height)
        photo = rounded_photo(width, height, self._fill, self._radius, self._outline)
        if photo is None:
            return
        self._photo = photo
        self.skin.configure(bg=self._parent_bg, width=8, height=8)
        if self._image_id is None:
            self._image_id = self.skin.create_image(0, 0, image=photo, anchor="nw")
        else:
            self.skin.itemconfigure(self._image_id, image=photo)
        self.skin.image = photo

    def apply_palette(self) -> None:
        self._fill = getattr(palette, self._fill_role)
        self._outline = palette.line
        self._parent_bg = getattr(palette, self._parent_role)
        self._size = (0, 0)
        self.configure(bg=self._parent_bg)
        self.skin.configure(bg=self._parent_bg)
        self.body.configure(bg=self._fill)
        if self._paint_job is None:
            self._paint_job = self.after_idle(self._paint)


def restyle(widget) -> None:
    backgrounds, foregrounds = _role_maps()
    options = (
        ("bg", backgrounds),
        ("fg", foregrounds),
        ("highlightbackground", backgrounds),
        ("highlightcolor", foregrounds),
        ("insertbackground", foregrounds),
        ("selectcolor", backgrounds),
        ("selectbackground", backgrounds),
        ("selectforeground", foregrounds),
        ("activebackground", backgrounds),
        ("activeforeground", foregrounds),
        ("troughcolor", backgrounds),
    )

    def walk(node) -> None:
        if isinstance(node, RoundCard):
            node.apply_palette()
        chosen = {}
        for option, mapping in options:
            try:
                value = str(node.cget(option))
            except tk.TclError:
                continue
            role = mapping.get(value.lower())
            if not role:
                continue
            chosen[option] = getattr(palette, role)
        if chosen:
            try:
                node.configure(**chosen)
            except tk.TclError:
                pass
        for child in list(node.winfo_children()):
            walk(child)

    walk(widget)


def _self_test() -> None:
    keys = set(SKINS["night"])
    for name, spec in SKINS.items():
        missing = keys - set(spec)
        extra = set(spec) - keys
        assert not missing and not extra, (name, missing, extra)
    assert len(SKINS) >= 8, len(SKINS)
    assert readable_on("#f6edd4") == "#101010"
    assert readable_on("#10141c") == "#ffffff"

    palette.use("night")
    assert not is_light()
    palette.use("light")
    assert is_light()
    palette.use("night")
    print("theme self-test ok", len(SKINS))


if __name__ == "__main__":
    _self_test()
