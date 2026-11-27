"""Capture the reference image and draw the zones that must stay empty. 100 % local.

    # 1. Reference from the webcam (median of 15 frames, station tidy, NOBODY in the field):
    python -m usecases.workstation.draw_zones --camera 0 --save data/workstation/reference.png
    # 2. Or from an existing image:
    python -m usecases.workstation.draw_zones --image data/workstation/reference.png

In the window: left click = add a point, Enter = close the polygon and name it,
Backspace = remove the last point, Escape = quit. When you quit, the YAML block to paste in
``usecases/workstation/config.yaml`` (``empty_zones:``) is printed, coordinates normalized.

tkinter is used because the platform installs the "headless" OpenCV, which has no window.
"""

from __future__ import annotations

import argparse
import base64
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog

import cv2
import numpy as np

MAX_WIDTH = 1200  # display size; coordinates are normalized, so scaling does not matter


def capture_reference(camera: int, frames: int = 15) -> np.ndarray:
    """Median of several webcam frames: removes the sensor noise of a single frame."""
    cap = cv2.VideoCapture(camera)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open webcam {camera}")
    shots = []
    for _ in range(frames + 5):
        ok, frame = cap.read()
        if ok:
            shots.append(frame)
    cap.release()
    if len(shots) < 5:
        raise SystemExit("The webcam returned too few frames")
    return np.median(np.stack(shots[5:]), axis=0).astype(np.uint8)  # skip warm-up frames


class ZoneDrawer:
    def __init__(self, image: np.ndarray) -> None:
        h, w = image.shape[:2]
        self.scale = min(1.0, MAX_WIDTH / w)
        self.dw, self.dh = int(w * self.scale), int(h * self.scale)
        shown = cv2.resize(image, (self.dw, self.dh))
        png = cv2.imencode(".png", shown)[1].tobytes()

        self.root = tk.Tk()
        self.root.title("Zones to keep empty - click points, Enter to close, Esc to quit")
        self.photo = tk.PhotoImage(data=base64.b64encode(png))
        self.canvas = tk.Canvas(self.root, width=self.dw, height=self.dh)
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        self.points: list[tuple[int, int]] = []
        self.zones: dict[str, list[tuple[float, float]]] = {}
        self.canvas.bind("<Button-1>", self.add_point)
        self.root.bind("<Return>", self.close_polygon)
        self.root.bind("<BackSpace>", self.undo)
        self.root.bind("<Escape>", lambda _: self.root.destroy())

    def add_point(self, event: tk.Event) -> None:
        self.points.append((event.x, event.y))
        self.redraw()

    def undo(self, _: tk.Event) -> None:
        if self.points:
            self.points.pop()
            self.redraw()

    def close_polygon(self, _: tk.Event) -> None:
        if len(self.points) < 3:
            return
        name = simpledialog.askstring("Zone name", "Name (e.g. keep_clear):", parent=self.root)
        if name:
            self.zones[name] = [
                (round(x / self.dw, 3), round(y / self.dh, 3)) for x, y in self.points
            ]
            self.canvas.create_polygon(*sum(self.points, ()), outline="red", fill="", width=3)
            self.canvas.create_text(*self.points[0], text=name, fill="red", anchor="sw")
        self.points = []
        self.redraw()

    def redraw(self) -> None:
        self.canvas.delete("current_polygon")
        for i, (x, y) in enumerate(self.points):
            self.canvas.create_oval(
                x - 4, y - 4, x + 4, y + 4, fill="yellow", tags="current_polygon"
            )
            if i:
                self.canvas.create_line(
                    *self.points[i - 1], x, y, fill="yellow", width=2, tags="current_polygon"
                )

    def run(self) -> dict[str, list[tuple[float, float]]]:
        self.root.mainloop()
        return self.zones


def to_yaml(zones: dict[str, list[tuple[float, float]]]) -> str:
    lines = ["  empty_zones:"]
    for name, points in zones.items():
        lines.append(f"    {name}: [" + ", ".join(f"[{x}, {y}]" for x, y in points) + "]")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--camera", type=int, help="webcam index")
    source.add_argument("--image", help="existing reference image")
    parser.add_argument("--save", help="where to write the captured reference image")
    args = parser.parse_args()

    if args.camera is not None:
        image = capture_reference(args.camera)
    else:
        image = cv2.imread(args.image)
        if image is None:
            raise SystemExit(f"Cannot read {args.image}")
    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(args.save, image)
        print(f"Reference image saved to {args.save}")

    zones = ZoneDrawer(image).run()
    if zones:
        print("\nPaste this under params: in usecases/workstation/config.yaml\n")
        print(to_yaml(zones))


if __name__ == "__main__":
    main()
