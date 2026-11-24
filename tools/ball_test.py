"""Self-test: build the real app, collapse to the ball, report what happened."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    import app as app_module

    try:
        window = app_module.App()
    except Exception:
        traceback.print_exc()
        return 1

    def sample(step: int = 0) -> None:
        ball = getattr(window, "ball", None)
        if ball is not None:
            print(f"t={step}s action={ball._action} auto={ball._auto} frames={len(ball.canvas.find_all())}", flush=True)
        if step < 20:
            window.after(1000, lambda: sample(step + 1))
        else:
            report()

    def report() -> None:
        ball = getattr(window, "ball", None)
        if ball is None:
            print("NO BALL OBJECT")
        else:
            print("fish ready:", ball.fish.ready, "| actions:", len(ball.fish.actions))
            print("mode:", ball._mode, "| size:", ball._win_w, "x", ball._win_h)
            print("mapped:", ball.winfo_ismapped(), "| viewable:", ball.winfo_viewable())
            print("position:", ball.winfo_x(), ball.winfo_y())
            print("canvas items:", len(ball.canvas.find_all()))
            print("action:", ball._action, "| bbox:", ball._fish_bbox)
            print("photo:", ball._photo is not None)
            try:
                if ball._photo is not None:
                    dump = Path(__file__).resolve().parent.parent / "_photo_dump.png"
                    ball._photo.write(str(dump), format="png")
                    print("photo dump:", dump)
                print("item bbox:", ball.canvas.bbox(ball._fish_item))
                print("item image:", ball.canvas.itemcget(ball._fish_item, "image")[:40])
                print("photo size:", ball._photo.width(), "x", ball._photo.height())
            except Exception:
                traceback.print_exc()
            try:
                from PIL import ImageGrab

                x, y = ball.winfo_x(), ball.winfo_y()
                w, h = ball._win_w, ball._win_h
                shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                path = Path(__file__).resolve().parent.parent / "_ball_shot.png"
                shot.save(path)
                print("screenshot:", path)
            except Exception:
                traceback.print_exc()
        window.destroy()

    def collapse() -> None:
        try:
            window.minimize_to_ball()
        except Exception:
            traceback.print_exc()
        window.after(35000, report)

    window.after(800, collapse)
    window.after(1500, lambda: sample(0))
    window.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
