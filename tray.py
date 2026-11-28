"""System tray icon (pystray). Menu actions are polled from the Tk thread."""

from __future__ import annotations

import threading

import pystray
from PIL import Image, ImageDraw


def _icon_image(size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 10, size - 4, size - 6), fill=(58, 118, 216, 255))
    draw.ellipse((size * 0.30, size * 0.36, size * 0.42, size * 0.48), fill=(255, 255, 255, 255))
    draw.ellipse((size * 0.58, size * 0.36, size * 0.70, size * 0.48), fill=(255, 255, 255, 255))
    draw.arc((size * 0.34, size * 0.46, size * 0.66, size * 0.70), 20, 160, fill=(255, 255, 255, 255), width=3)
    draw.polygon([(size * 0.18, size * 0.22), (size * 0.30, size * 0.10), (size * 0.34, size * 0.26)], fill=(58, 118, 216, 255))
    return image


class Tray:
    def __init__(self, app) -> None:
        self.app = app
        self.action: str | None = None
        self.icon = None
        self.thread: threading.Thread | None = None

    def set_action(self, action: str | None) -> None:
        self.action = action

    def consume(self) -> str | None:
        action = self.action
        self.action = None
        return action

    def show(self) -> None:
        if self.icon is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("打开主界面", lambda *_: self.set_action("open"), default=True),
            pystray.MenuItem("显示桌宠", lambda *_: self.set_action("ball")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda *_: self.set_action("quit")),
        )
        self.icon = pystray.Icon("jobdesk", _icon_image(), "作业看台", menu)
        self.thread = threading.Thread(target=self.icon.run, daemon=True)
        self.thread.start()

    def hide(self) -> None:
        if self.icon is None:
            return
        try:
            self.icon.stop()
        except Exception:
            pass
        self.icon = None
        self.thread = None
