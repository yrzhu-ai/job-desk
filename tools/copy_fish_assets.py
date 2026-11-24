"""Copy the dsh-pet webm animations (and ffmpeg) into the project.

Result:
    pets/fish/webm/<action>.webm        (original 640x360 VP9-alpha files)
    pets/fish/animations.json           { "actions": {name: {}}, "width":640, "height":360 }
    bin/ffmpeg.exe                      decoder used at runtime

Run:  python tools/copy_fish_assets.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
SRC = Path.home() / ".dsh" / "profiles" / "desktop" / "node_modules" / "@tuweizhi" / "dsh-pet" / "assets" / "webm"
OUT = ROOT / "pets" / "fish"
BIN = ROOT / "bin"


def main() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"source not found: {SRC}")
    webm_dir = OUT / "webm"
    webm_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.webm"))
    for file in files:
        target = webm_dir / file.name
        if not target.exists() or target.stat().st_size != file.stat().st_size:
            shutil.copy2(file, target)
    manifest = {
        "width": 640,
        "height": 360,
        "fps": 24,
        "actions": {file.stem: {} for file in files},
    }
    (OUT / "animations.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    BIN.mkdir(exist_ok=True)
    ff = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if ff.exists():
        shutil.copy2(ff, BIN / "ffmpeg.exe")
    size = sum(p.stat().st_size for p in OUT.rglob("*.webm"))
    print(f"{len(files)} actions, {size / 1024 / 1024:.1f} MB webm")
    print(f"ffmpeg -> {BIN / 'ffmpeg.exe'}")


if __name__ == "__main__":
    main()
