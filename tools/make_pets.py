"""Turn the bundled free assets into pet skins (pets/<name>/<state>/*.png).

Sources (all free to use):
  Cat sprites - Shepardskin, OpenGameArt (no attribution needed)
  Pixel ghost - OpenGameArt (CC0)
  Slime       - OpenGameArt (CC0)

Run:  python tools/make_pets.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "_assets"
OUT = ROOT / "pets"
SIDE = 128


def _matte_to_alpha(image: Image.Image, matte=(164, 117, 160), tolerance: int = 26) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a and abs(r - matte[0]) < tolerance and abs(g - matte[1]) < tolerance and abs(b - matte[2]) < tolerance:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def _fit(image: Image.Image, side: int = SIDE) -> Image.Image:
    image = image.copy()
    box = image.getbbox()
    if box:
        image = image.crop(box)
    scale = min(side / max(image.width, image.height), 1.8)
    return image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)


def _pad(image: Image.Image, side: int = SIDE) -> Image.Image:
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)
    return canvas


def _save(folder: Path, frames: list[Image.Image]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, 1):
        frame.save(folder / f"{index}.png")


def _config(name: str, frame_ms: dict, hold_ms: dict) -> None:
    (OUT / name / "pet.json").write_text(
        json.dumps({"frame_ms": frame_ms, "hold_ms": hold_ms}, indent=2),
        encoding="utf-8",
    )


def make_cat() -> None:
    gif = Image.open(ASSETS / "cat" / "cat sprite" / "catwalkx4.gif")
    walk = [_pad(_fit(_matte_to_alpha(frame.convert("RGBA")))) for frame in ImageSequence.Iterator(gif)]
    _save(OUT / "cat" / "idle", walk)
    _save(OUT / "cat" / "happy", [frame.transpose(Image.FLIP_LEFT_RIGHT) for frame in walk])
    _save(OUT / "cat" / "sad", [ImageOps.grayscale(frame).convert("RGBA") for frame in walk])
    _save(OUT / "cat" / "trick", [frame.rotate(angle, resample=Image.BICUBIC) for angle in (-14, 0, 14, 0) for frame in [walk[0]]])
    _config("cat", {"idle": 120, "happy": 90, "sad": 170, "trick": 120}, {"happy": 2800, "sad": 3000, "trick": 4500})


def make_ghost() -> None:
    base = _pad(_fit(Image.open(ASSETS / "ghost_pixel.png").convert("RGBA")))
    _save(OUT / "ghost" / "idle", [base])
    _save(OUT / "ghost" / "happy", [base.rotate(angle, resample=Image.BICUBIC) for angle in (-7, 7)])
    _save(OUT / "ghost" / "sad", [ImageOps.grayscale(base).convert("RGBA").rotate(-9, resample=Image.BICUBIC)])
    _save(OUT / "ghost" / "trick", [base.rotate(-16, resample=Image.BICUBIC), base.rotate(16, resample=Image.BICUBIC)])
    _config("ghost", {"idle": 240, "happy": 120, "sad": 200, "trick": 160}, {"happy": 2800, "sad": 3000, "trick": 4200})


def make_slime() -> None:
    image = Image.open(ASSETS / "slime.png").convert("RGBA")
    box = image.getbbox()
    if box:
        image = image.crop(box)
    image = _fit(image, 110)

    def squash(factor: float) -> Image.Image:
        width = max(1, int(image.width * (1.0 / factor)))
        height = max(1, int(image.height * factor))
        return _pad(image.resize((width, height), Image.LANCZOS))

    _save(OUT / "slime" / "idle", [squash(0.94), squash(1.0), squash(1.06), squash(1.0)])
    _save(OUT / "slime" / "happy", [squash(0.88), squash(1.10), squash(0.92), squash(1.08)])
    _save(OUT / "slime" / "sad", [squash(0.86), squash(0.9)])
    _save(OUT / "slime" / "trick", [squash(0.8), squash(1.16), squash(0.85), squash(1.1)])
    _config("slime", {"idle": 170, "happy": 110, "sad": 260, "trick": 150}, {"happy": 2800, "sad": 3000, "trick": 4000})


def main() -> None:
    if not ASSETS.is_dir():
        raise SystemExit("missing _assets folder")
    OUT.mkdir(exist_ok=True)
    make_cat()
    make_ghost()
    make_slime()
    for skin in sorted(p.name for p in OUT.iterdir() if p.is_dir()):
        states = sorted(p.name for p in (OUT / skin).iterdir() if p.is_dir())
        counts = ", ".join(f"{s}={len(list((OUT / skin / s).glob('*.png')))}" for s in states)
        print(f"{skin:8} {counts}")


if __name__ == "__main__":
    main()
