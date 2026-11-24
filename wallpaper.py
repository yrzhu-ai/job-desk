"""Optional user background image, tiled and blended into the theme colour."""

from __future__ import annotations

import tkinter as tk

from PIL import Image, ImageTk


FIT_MODES = ("fill", "fit", "stretch", "tile", "center")


class Wallpaper:
    """Loads one picture and produces fitted PhotoImages for canvases."""

    def __init__(self) -> None:
        self.path = ""
        self.mode = "fill"
        self._source: Image.Image | None = None
        self._cache: dict[tuple, ImageTk.PhotoImage] = {}

    @property
    def ready(self) -> bool:
        return self._source is not None

    def load(self, path: str, mode: str | None = None) -> bool:
        text = str(path or "").strip()
        self._cache.clear()
        self.path = ""
        self._source = None
        if mode:
            self.mode = mode if mode in FIT_MODES else "fill"
        if not text:
            return True
        try:
            image = Image.open(text)
            image.load()
        except Exception:
            return False
        self.path = text
        self._source = image.convert("RGBA")
        return True

    def _fitted(self, width: int, height: int) -> Image.Image:
        """Scale the picture for the chosen fit mode into a width x height sheet."""
        source = self._source
        assert source is not None
        mode = self.mode
        if mode == "stretch":
            return source.resize((width, height), Image.LANCZOS)
        if mode == "tile":
            patch = source
            side = max(patch.width, patch.height)
            if side > 240:
                factor = side / 240
                patch = patch.resize((max(1, int(patch.width / factor)), max(1, int(patch.height / factor))), Image.LANCZOS)
            sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            for y in range(0, height, patch.height):
                for x in range(0, width, patch.width):
                    sheet.paste(patch, (x, y))
            return sheet
        if mode == "center":
            sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            sheet.paste(source, ((width - source.width) // 2, (height - source.height) // 2))
            return sheet
        if mode == "fit":
            scale = min(width / source.width, height / source.height)
            size = (max(1, int(source.width * scale)), max(1, int(source.height * scale)))
            sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            sheet.paste(source.resize(size, Image.LANCZOS), ((width - size[0]) // 2, (height - size[1]) // 2))
            return sheet
        # fill (and span): cover the area, crop the overflow
        scale = max(width / source.width, height / source.height)
        size = (max(width, int(source.width * scale)), max(height, int(source.height * scale)))
        scaled = source.resize(size, Image.LANCZOS)
        left = (scaled.width - width) // 2
        top = (scaled.height - height) // 2
        return scaled.crop((left, top, left + width, top + height))

    def tile(self, master: tk.Misc, width: int, height: int, base: str, alpha: float = 0.22) -> tk.PhotoImage | None:
        """A width x height sheet of the picture, blended over `base` at `alpha`."""
        if not self.ready or width <= 1 or height <= 1:
            return None
        key = (width, height, base, round(alpha, 3), self.mode)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sheet = self._fitted(width, height)
        rgb = master.winfo_rgb(base)
        tint = Image.new("RGBA", (width, height), (rgb[0] // 257, rgb[1] // 257, rgb[2] // 257, 255))
        layer = sheet.convert("RGBA")
        layer.putalpha(layer.getchannel("A").point(lambda value: int(value * alpha)))
        blended = Image.alpha_composite(tint, layer)
        try:
            photo = ImageTk.PhotoImage(blended, master=master)
        except Exception:
            return None
        if len(self._cache) > 12:
            self._cache.clear()
        self._cache[key] = photo
        return photo
