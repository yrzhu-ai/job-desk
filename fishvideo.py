"""Play the original dsh-pet webm animations (640x360, VP9 + alpha).

PyAV's default vp9 decoder drops the alpha plane, so packets are fed to the
libvpx-vp9 decoder explicitly. Frames are produced as RGBA numpy arrays on
demand (about 1 ms each).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import av
import numpy  # noqa: F401  (PyInstaller needs the explicit import to bundle av's dependency)

from store import data_dir

IDLE_ACTIONS = ("待机呼吸", "东张西望", "原地小憩沉眠", "打瞌睡", "哼歌", "照镜子")


def _roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent)
        base = getattr(sys, "_MEIPASS", "")
        if base:
            roots.append(Path(base))
    roots.append(Path(data_dir()))
    roots.append(Path(__file__).resolve().parent)
    return roots


def pack_root() -> Path | None:
    for root in _roots():
        candidate = root / "pets" / "fish"
        if (candidate / "animations.json").is_file() and (candidate / "webm").is_dir():
            return candidate
    return None


class FishVideo:
    """Lazily opens one webm at a time and yields RGBA frames."""

    def __init__(self) -> None:
        self.folder = pack_root()
        self.actions: list[str] = []
        self.width = 640
        self.height = 360
        self.fps = 24
        self._bbox: dict[str, tuple[int, int, int, int]] = {}
        self._load()

    def _load(self) -> None:
        if self.folder is None:
            return
        try:
            data = json.loads((self.folder / "animations.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        actions = data.get("actions") if isinstance(data, dict) else None
        if isinstance(actions, dict):
            self.actions = sorted(actions)
        self.width = int(data.get("width") or 640)
        self.height = int(data.get("height") or 360)
        self.fps = int(data.get("fps") or 24)

    @property
    def ready(self) -> bool:
        return bool(self.actions) and self.folder is not None

    def names(self) -> list[str]:
        return list(self.actions)

    def exists(self, action: str) -> bool:
        return self.folder is not None and (self.folder / "webm" / f"{action}.webm").is_file()

    def pick_idle(self) -> str:
        options = [name for name in self.actions if name in IDLE_ACTIONS]
        return random.choice(options) if options else random.choice(self.actions)

    def pick_random(self) -> str:
        return random.choice(self.actions)

    def clip_bbox(self, action: str) -> tuple[int, int, int, int] | None:
        """Union of the visible area over the first frames, so we can crop the empty canvas."""
        cached = self._bbox.get(action)
        if cached is not None:
            return cached
        box = None
        seen = 0
        for arr in self.frames(action):
            seen += 1
            alpha = arr[:, :, 3]
            rows = (alpha > 40).any(axis=1)
            cols = (alpha > 40).any(axis=0)
            if rows.any() and cols.any():
                top = int(rows.argmax())
                bottom = int(len(rows) - rows[::-1].argmax())
                left = int(cols.argmax())
                right = int(len(cols) - cols[::-1].argmax())
                if box is None:
                    box = [left, top, right, bottom]
                else:
                    box = [min(box[0], left), min(box[1], top), max(box[2], right), max(box[3], bottom)]
            if seen >= 16:
                break
        if box is None:
            return None
        pad = 4
        result = (
            max(0, box[0] - pad),
            max(0, box[1] - pad),
            min(self.width, box[2] + pad),
            min(self.height, box[3] + pad),
        )
        if len(self._bbox) > 120:
            self._bbox.clear()
        self._bbox[action] = result
        return result

    def frames(self, action: str):
        """Yield RGBA arrays for the whole clip."""
        if self.folder is None:
            return
        path = self.folder / "webm" / f"{action}.webm"
        if not path.is_file():
            return
        container = av.open(str(path))
        try:
            stream = container.streams.video[0]
            decoder = av.CodecContext.create("libvpx-vp9", "r")
            for packet in container.demux(stream):
                for frame in decoder.decode(packet):
                    if not frame.width:
                        continue
                    yield frame.to_ndarray(format="rgba")
        finally:
            container.close()
