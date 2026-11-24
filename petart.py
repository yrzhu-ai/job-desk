"""Sprite-art support for the floating pet ball.

Skins are folders of PNG frames:

    pets/<skin>/idle/1.png 2.png ...     (required)
    pets/<skin>/happy/1.png ...          (job finished)
    pets/<skin>/sad/1.png ...            (job failed)
    pets/<skin>/trick/1.png ...          (idle show-off)
    pets/<skin>/pet.json                 (optional timings)

Lookup order: exe folder -> bundled (_MEIPASS) -> %APPDATA%/LinuxJobDesk -> source
folder. A plain `pet/` folder (the old single-skin layout) still works.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import tkinter as tk

from store import data_dir
STATES = ("idle", "happy", "sad", "trick", "drag")
DEFAULT_MS = {"idle": 260, "happy": 110, "sad": 150, "trick": 110, "drag": 120}
DEFAULT_HOLD = {"idle": 0, "happy": 3200, "sad": 3200, "trick": 5000, "drag": 0}
MAX_SIDE = 180


def _natural(path: Path) -> tuple:
    return tuple(int(piece) if piece.isdigit() else piece.lower() for piece in re.split(r"(\d+)", path.stem))


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


def list_skins() -> list[str]:
    names: set[str] = set()
    for root in _roots():
        folder = root / "pets"
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if (child / "idle").is_dir():
                names.add(child.name)
    return sorted(names)


def find_skin(name: str) -> Path | None:
    if not name:
        return None
    for root in _roots():
        candidate = root / "pets" / name
        if (candidate / "idle").is_dir():
            return candidate
    return None


def legacy_folder() -> Path | None:
    for root in _roots():
        candidate = root / "pet"
        if (candidate / "idle").is_dir():
            return candidate
    return None


class PetArt:
    """Loads frames once; `ready` is False when no images were found."""

    def __init__(self, root: tk.Misc, folder: Path | None = None) -> None:
        self.root = root
        self.folder = Path(folder) if folder else (legacy_folder() or _roots()[0] / "pet")
        self.config = self._config()
        self.frames: dict[str, list[tk.PhotoImage]] = {}
        self.ready = False
        self.width = 0
        self.height = 0
        self._load()

    def _config(self) -> dict:
        path = self.folder / "pet.json"
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _state_files(self, state: str) -> list[Path]:
        folder = self.folder / state
        if folder.is_dir():
            files = sorted(folder.glob("*.png"), key=_natural)
            if files:
                return files
        return sorted(self.folder.glob(f"{state}*.png"), key=_natural)

    def _load(self) -> None:
        for state in STATES:
            files = self._state_files(state)
            if not files:
                continue
            images: list[tk.PhotoImage] = []
            for path in files[:40]:
                try:
                    image = tk.PhotoImage(master=self.root, file=str(path))
                except tk.TclError:
                    continue
                if image.width() > MAX_SIDE or image.height() > MAX_SIDE:
                    factor = max(1, max(image.width(), image.height()) // MAX_SIDE)
                    image = image.subsample(factor, factor)
                images.append(image)
            if images:
                self.frames[state] = images
                self.width = max(self.width, images[0].width())
                self.height = max(self.height, images[0].height())
        self.ready = "idle" in self.frames and self.width > 0 and self.height > 0
        if self.ready:
            self.width = int(self.config.get("width") or self.width)
            self.height = int(self.config.get("height") or self.height)

    def ms(self, state: str) -> int:
        rates = self.config.get("frame_ms")
        if isinstance(rates, dict) and state in rates:
            try:
                return max(40, int(rates[state]))
            except (TypeError, ValueError):
                pass
        return DEFAULT_MS.get(state, 140)

    def hold(self, state: str) -> int:
        holds = self.config.get("hold_ms")
        if isinstance(holds, dict) and state in holds:
            try:
                return max(0, int(holds[state]))
            except (TypeError, ValueError):
                pass
        return DEFAULT_HOLD.get(state, 3000)

    def images(self, state: str) -> list[tk.PhotoImage]:
        return self.frames.get(state) or self.frames.get("idle") or []
