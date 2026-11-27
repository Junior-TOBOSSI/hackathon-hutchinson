"""Live visual test of the SH17 PPE model on a webcam. Faces are ALWAYS hidden.

Usage (from the repository root, venv activated):
    python usecases/safety/notebooks/webcam_preview.py
    python usecases/safety/notebooks/webcam_preview.py --camera 1 --weights data/models/safety/x.pt

Keys: q = quit, + / - = raise / lower the display confidence threshold.

Phone: a second, generic model (YOLOv8n trained on COCO, class "cell phone", no training
needed) finds phones. A phone close to a hand, a gloved hand or a head counts as "in use"
(red); a phone far from everybody (lying on the bench) is only shown (orange) - that case
belongs to the workstation use case. --no-phone turns it off.

Privacy (GDPR, AGENTS.md rule "never store or display a face"):
- faces are pixelated BEFORE anything is drawn or shown;
- face and head boxes are hidden even with a low confidence (PRIVACY_CONF), lower than the
  display threshold: when in doubt, we hide;
- the lower part of every head box is also hidden, in case a face is not detected as "face";
- a person with no face and no head detected gets the top of their box hidden;
- nothing is written to disk: no image, no video.
"""

from __future__ import annotations

import argparse
import time

import cv2
import numpy as np
from ultralytics import YOLO

# Classes drawn on screen (SH17 name -> BGR colour).
DRAWN_CLASSES = {
    "person": (255, 255, 255),
    "helmet": (0, 215, 255),
    "safety-vest": (0, 140, 255),
    "glasses": (255, 200, 0),
    "gloves": (0, 200, 0),
    "shoes": (200, 0, 200),
    "head": (160, 160, 160),
    "hands": (120, 220, 120),
    "foot": (220, 120, 220),
    "vest": (0, 140, 255),  # name in our retrained model
}
PHONE_CLASS = "cell phone"  # COCO class name
PHONE_ZONE = ("hands", "gloves", "head")  # a phone near one of these is "in use"
PHONE_MARGIN = 0.5  # phone box widened by 50% of its size before checking the contact
PHONE_IN_USE_COLOR, PHONE_IDLE_COLOR = (0, 0, 255), (0, 165, 255)
FACE_CLASS, HEAD_CLASS, PERSON_CLASS = "face", "head", "person"
PRIVACY_CONF = 0.10  # faces and heads are hidden from this confidence on
HEAD_HIDDEN_PART = 0.6  # lower 60% of a head box is hidden (the top keeps the helmet visible)
PERSON_HIDDEN_PART = 0.3  # top 30% of a person box, when no face/head was found inside it
CAMERA_TIMEOUT_S = 3.0  # give up after this long without any image


def pixelate(image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    """Replace a region by big blocks, in place. Unlike a light blur, it cannot be undone."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    region = image[y1:y2, x1:x2]
    small = cv2.resize(region, (6, 6), interpolation=cv2.INTER_AREA)
    image[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


def center_inside(inner: tuple[int, ...], outer: tuple[int, ...]) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def hide_faces(image: np.ndarray, detections: list[tuple[str, float, tuple[int, ...]]]) -> None:
    """Pixelate faces, the lower part of heads, and the top of persons with no head found."""
    kept = [(name, box) for name, conf, box in detections if conf >= PRIVACY_CONF]
    face_or_head = [box for name, box in kept if name in (FACE_CLASS, HEAD_CLASS)]
    for name, (x1, y1, x2, y2) in kept:
        margin = int(0.15 * (x2 - x1))  # a bit wider than the box, to be safe
        if name == FACE_CLASS:
            pixelate(image, x1 - margin, y1 - margin, x2 + margin, y2 + margin)
        elif name == HEAD_CLASS:
            top = y2 - int(HEAD_HIDDEN_PART * (y2 - y1))
            pixelate(image, x1 - margin, top, x2 + margin, y2 + margin)
        elif name == PERSON_CLASS and not any(
            center_inside(b, (x1, y1, x2, y2)) for b in face_or_head
        ):
            # Fallback: a person whose face/head was missed. The head is in the top part of
            # the box, so hide it. The helmet may be hidden too: privacy comes first.
            pixelate(image, x1, y1, x2, y1 + int(PERSON_HIDDEN_PART * (y2 - y1)))


def draw(image: np.ndarray, detections, threshold: float) -> list[str]:
    """Draw the PPE boxes above the threshold; return the names seen."""
    seen = []
    for name, conf, (x1, y1, x2, y2) in detections:
        if name not in DRAWN_CLASSES or conf < threshold:
            continue
        seen.append(name)
        color = DRAWN_CLASSES[name]
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        cv2.putText(image, f"{name} {conf:.2f}", (x1, max(14, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)  # fmt: skip
    return seen


def touches(a: tuple[int, ...], b: tuple[int, ...], margin: float) -> bool:
    """True if box a, widened by margin x its own size, overlaps box b."""
    dx, dy = margin * (a[2] - a[0]), margin * (a[3] - a[1])
    return a[0] - dx < b[2] and b[0] < a[2] + dx and a[1] - dy < b[3] and b[1] < a[3] + dy


def phones_in_use(phones, detections, threshold: float) -> list[bool]:
    """For each phone: is it held or at the ear (close to a hand, gloved hand or head)?"""
    zones = [box for name, conf, box in detections if name in PHONE_ZONE and conf >= threshold]
    return [any(touches(box, z, PHONE_MARGIN) for z in zones) for _, box in phones]


def draw_phones(image: np.ndarray, phones, in_use: list[bool]) -> None:
    for (conf, (x1, y1, x2, y2)), used in zip(phones, in_use, strict=True):
        color = PHONE_IN_USE_COLOR if used else PHONE_IDLE_COLOR
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3 if used else 2)
        label = f"PHONE IN USE {conf:.2f}" if used else f"phone {conf:.2f}"
        cv2.putText(image, label, (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def draw_banner(
    image: np.ndarray, fps: float, threshold: float, seen: list[str], phone_alert: bool = False
) -> None:
    counts = {n: seen.count(n) for n in DRAWN_CLASSES if n in seen}
    text = ", ".join(f"{n} x{c}" for n, c in counts.items()) or "nothing detected"
    cv2.rectangle(image, (0, 0), (image.shape[1], 48), (0, 0, 0), -1)
    status = f"{fps:4.1f} FPS | threshold {threshold:.2f} | q quit, +/- threshold"
    cv2.putText(image, status, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(image, text, (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    if phone_alert:
        x = image.shape[1] - 190
        cv2.putText(
            image, "PHONE IN USE", (x, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, PHONE_IN_USE_COLOR, 2
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # yolov8s: best ready-made option on SH17 val (mAP50 0.56 vs 0.53 for n), ~60 ms on CPU.
    parser.add_argument("--weights", default="data/models/safety/sh17_yolov8s.pt")
    parser.add_argument("--camera", type=int, default=0, help="webcam index")
    parser.add_argument("--threshold", type=float, default=0.25, help="display confidence")
    parser.add_argument("--imgsz", type=int, default=640, help="model input size")
    parser.add_argument("--phone-weights", default="data/models/yolov8n_coco.pt")
    parser.add_argument("--phone-conf", type=float, default=0.30, help="phone threshold")
    parser.add_argument("--no-phone", action="store_true", help="do not look for phones")
    args = parser.parse_args(argv)

    model = YOLO(args.weights)
    names = {i: str(n).lower() for i, n in model.names.items()}
    phone_model = None if args.no_phone else YOLO(args.phone_weights)
    phone_id = None
    if phone_model is not None:
        phone_id = next(i for i, n in phone_model.names.items() if n == PHONE_CLASS)
    capture = cv2.VideoCapture(args.camera)
    if not capture.isOpened():
        raise SystemExit(
            f"Cannot open camera {args.camera}. On macOS, allow camera access for the "
            "Terminal / VS Code (System Settings > Privacy & Security > Camera)."
        )

    threshold, fps, last = args.threshold, 0.0, time.perf_counter()
    window = "SH17 PPE preview (faces hidden)"
    failed_since = None  # macOS cameras often send empty frames while warming up
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                failed_since = failed_since or time.perf_counter()
                if time.perf_counter() - failed_since > CAMERA_TIMEOUT_S:
                    print(f"No image from the camera for {CAMERA_TIMEOUT_S} s, stopping.")
                    break
                time.sleep(0.05)
                continue
            failed_since = None
            # Low confidence on purpose: faces must be found even when the model hesitates.
            result = model.predict(frame, conf=PRIVACY_CONF, imgsz=args.imgsz,
                                   device="cpu", verbose=False)[0]  # fmt: skip
            boxes = result.boxes
            detections = [
                (names[int(c)], float(s), tuple(int(v) for v in xyxy))
                for c, s, xyxy in zip(boxes.cls, boxes.conf, boxes.xyxy, strict=True)
            ]
            phones = []
            if phone_model is not None:  # only the phone class of the COCO model
                found = phone_model.predict(frame, conf=args.phone_conf, classes=[phone_id],
                                            imgsz=args.imgsz, device="cpu", verbose=False)[0]  # fmt: skip
                phones = [
                    (float(s), tuple(int(v) for v in xyxy))
                    for s, xyxy in zip(found.boxes.conf, found.boxes.xyxy, strict=True)
                ]
            hide_faces(frame, detections)  # FIRST: nothing is shown before this line
            seen = draw(frame, detections, threshold)
            in_use = phones_in_use(phones, detections, threshold)
            draw_phones(frame, phones, in_use)

            now = time.perf_counter()
            fps = 0.9 * fps + 0.1 / max(now - last, 1e-6)  # smoothed frame rate
            last = now
            draw_banner(frame, fps, threshold, seen, phone_alert=any(in_use))
            cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key in (ord("+"), ord("=")):
                threshold = min(0.95, threshold + 0.05)
            if key == ord("-"):
                threshold = max(PRIVACY_CONF, threshold - 0.05)
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
