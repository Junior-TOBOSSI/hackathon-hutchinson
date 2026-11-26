"""Generate test photos of a station from its reference image, with the expected answer.

    python -m usecases.workstation.make_variants --station poste1 [--data-root data] [--n 10]

For a station described in ``stations/<name>.yaml`` (reference source, empty zones,
element slots), it writes to ``<data-root>/processed/workstation/<name>/``:

- ``reference.png``       : the reference (cleaned screenshot, or copy of the photo)
- ``preview.png``         : the reference with its zones (red) and slots (cyan) drawn
- ``variants/*.png``      : the generated "photos at the start of the shift"
- ``variants/labels.json``: for each photo, the expected decision and problems

Variants (every one then gets a random CAMERA JITTER: small shift / rotation / zoom,
brightness, noise, blur, JPEG compression, so that the alignment is always exercised):

| kind                | what is done                                  | expected            |
|---------------------|-----------------------------------------------|---------------------|
| ok                  | nothing                                       | conforme            |
| object_outside      | an object pasted outside zones and slots      | conforme            |
| missing_<slot>      | the element of the slot erased (inpainting)   | anomalie (missing)  |
| object_in_<zone>    | an element of the station pasted in the zone  | anomalie (@zone)    |
| person_in_<zone>    | a person cut-out pasted in the zone           | anomalie (@zone)    |

Everything runs locally (OpenCV; Ultralytics only to cut out a person).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from usecases.workstation.clean_capture import clean_capture
from usecases.workstation.zones import polygon_mask, validate_polygon

log = logging.getLogger(__name__)
STATIONS_DIR = Path(__file__).parent / "stations"


# ------------------------------------------------------------------ station


def load_station(name: str) -> dict[str, Any]:
    path = STATIONS_DIR / f"{name}.yaml"
    station = yaml.safe_load(path.read_text(encoding="utf-8"))
    for kind in ("empty_zones", "element_slots"):
        station[kind] = {n: validate_polygon(n, p) for n, p in (station.get(kind) or {}).items()}
    return station


def station_dir(station: dict[str, Any], data_root: Path) -> Path:
    return data_root / "processed" / "workstation" / station["name"]


def prepare_reference(station: dict[str, Any], data_root: Path, force: bool = False) -> Path:
    """Create the reference image of the station from its raw source (once)."""
    out = station_dir(station, data_root) / "reference.png"
    if out.exists() and not force:
        return out
    source = data_root / station["source"]
    image = cv2.imread(str(source))
    if image is None:
        raise FileNotFoundError(f"Raw image not found: {source}")
    if station.get("prepare", "copy") == "clean_capture":
        image, _ = clean_capture(image)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image)
    return out


def draw_regions(image: np.ndarray, station: dict[str, Any]) -> np.ndarray:
    """Copy of the image with the empty zones (red) and element slots (cyan) drawn."""
    out = image.copy()
    h, w = out.shape[:2]
    for kind, colour in (("empty_zones", (0, 0, 255)), ("element_slots", (255, 255, 0))):
        for name, polygon in station[kind].items():
            pts = (np.array(polygon) * [w - 1, h - 1]).astype(np.int32)
            cv2.polylines(out, [pts], True, colour, 2)
            cv2.putText(out, name, (int(pts[0][0]) + 3, int(pts[0][1]) + 14), 0, 0.45, colour, 1)
    return out


# ------------------------------------------------------------------ image operations


@dataclass
class Patch:
    """An object cut out of an image: pixels + mask (uint8, 255 inside)."""

    image: np.ndarray
    mask: np.ndarray
    name: str


def slot_patches(reference: np.ndarray, station: dict[str, Any]) -> list[Patch]:
    """Each element of the station, cut out of the reference along its slot polygon."""
    patches = []
    for name, polygon in station["element_slots"].items():
        mask = polygon_mask(polygon, reference.shape[:2])
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            continue
        box = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        patches.append(Patch(reference[box].copy(), mask[box].astype(np.uint8) * 255, name))
    return patches


def person_patch(
    images: list[np.ndarray], weights: str = "data/models/workstation/yolo26n-seg.pt"
) -> Patch | None:
    """Biggest person found by a segmentation model in the images, or None.

    The operator of station 1 is seen from above and cut by the image border: the model
    only finds him at a high input size (1280) and a low confidence (0.1). That is fine
    here: the detection is only used to CUT OUT a person, it decides nothing.
    """
    try:
        from ultralytics import YOLO, settings

        from usecases.workstation.detector import resolve_weights
    except ImportError:
        log.warning("ultralytics not installed: no person variants")
        return None
    settings.update({"sync": False})
    model = YOLO(str(resolve_weights(weights)))
    best: Patch | None = None
    for image in images:
        result = model.predict(image, classes=[0], conf=0.1, imgsz=1280, verbose=False)[0]
        if result.masks is None:
            continue
        for polygon in result.masks.xy:
            if len(polygon) < 3:
                continue
            mask = np.zeros(image.shape[:2], np.uint8)
            cv2.fillPoly(mask, [polygon.astype(np.int32)], 255)
            x, y, w, h = cv2.boundingRect(polygon.astype(np.int32))
            if best is None or mask.sum() > best.mask.sum():
                box = (slice(y, y + h), slice(x, x + w))
                best = Patch(image[box].copy(), mask[box], "person")
    return best


def erase_region(image: np.ndarray, polygon: list, radius: int = 9) -> np.ndarray:
    """Erase what is inside the polygon and fill it from the surroundings (inpainting)."""
    mask = polygon_mask(polygon, image.shape[:2]).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))
    return cv2.inpaint(image, mask, radius, cv2.INPAINT_TELEA)


def paste(
    image: np.ndarray,
    patch: Patch,
    region: np.ndarray,
    rng: np.random.Generator,
    max_fill: float = 0.6,
    tries: int = 200,
) -> np.ndarray | None:
    """Paste the patch at a random place fully inside ``region`` (bool mask). The patch is
    scaled to at most ``max_fill`` of the region size; edges are feathered."""
    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return None
    rw, rh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    ph, pw = patch.mask.shape
    scale = min(max_fill * rw / pw, max_fill * rh / ph) * rng.uniform(0.6, 1.0)
    pw2, ph2 = max(8, int(pw * scale)), max(8, int(ph * scale))
    obj = cv2.resize(patch.image, (pw2, ph2), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(patch.mask, (pw2, ph2), interpolation=cv2.INTER_NEAREST) > 127
    for _ in range(tries):
        x = int(rng.integers(xs.min(), max(xs.min() + 1, xs.max() - pw2 + 1)))
        y = int(rng.integers(ys.min(), max(ys.min() + 1, ys.max() - ph2 + 1)))
        window = region[y : y + ph2, x : x + pw2]
        if window.shape != mask.shape or window[mask].mean() < 0.98:
            continue
        alpha = cv2.GaussianBlur(mask.astype(np.float32), (5, 5), 0)[..., None]
        out = image.copy()
        roi = out[y : y + ph2, x : x + pw2].astype(np.float32)
        out[y : y + ph2, x : x + pw2] = (alpha * obj + (1 - alpha) * roi).astype(np.uint8)
        return out
    return None


def camera_jitter(
    image: np.ndarray, rng: np.random.Generator, strength: float = 0.02
) -> np.ndarray:
    """Simulate another shot of the same camera: small perspective change, light, noise."""
    h, w = image.shape[:2]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    shift = rng.uniform(-strength, strength, (4, 2)) * [w, h]
    moved = (corners + shift).astype(np.float32)
    shot = cv2.warpPerspective(
        image, cv2.getPerspectiveTransform(corners, moved), (w, h), borderMode=cv2.BORDER_REFLECT
    )
    shot = cv2.convertScaleAbs(shot, alpha=rng.uniform(0.85, 1.15), beta=rng.uniform(-15, 15))
    shot = np.clip(shot + rng.normal(0, rng.uniform(1, 4), shot.shape), 0, 255).astype(np.uint8)
    if rng.random() < 0.5:
        shot = cv2.GaussianBlur(shot, (3, 3), 0)
    ok, jpg = cv2.imencode(".jpg", shot, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(70, 95))])
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR)


# ------------------------------------------------------------------ variants


@dataclass
class Variant:
    name: str
    kind: str
    image: np.ndarray
    expected: str  # conforme | anomalie
    problems: list[str] = field(default_factory=list)


def generate(
    reference: np.ndarray,
    station: dict[str, Any],
    rng: np.random.Generator,
    n: int = 10,
    foreign: list[Patch] | None = None,
    person: Patch | None = None,
    jitter: float = 0.02,
) -> list[Variant]:
    """All the variants of one station (see the module docstring)."""
    shape = reference.shape[:2]
    zones = {z: polygon_mask(p, shape) for z, p in station["empty_zones"].items()}
    slots = {s: polygon_mask(p, shape) for s, p in station["element_slots"].items()}
    patches = slot_patches(reference, station) + list(foreign or [])
    judged = np.zeros(shape, bool)
    for m in [*zones.values(), *slots.values()]:
        judged |= cv2.dilate(m.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    outside = ~judged

    out: list[Variant] = []

    def add(kind: str, image: np.ndarray | None, expected: str, problems: list[str]) -> None:
        if image is not None:
            name = f"{kind}_{sum(v.kind == kind for v in out):03d}"
            out.append(Variant(name, kind, camera_jitter(image, rng, jitter), expected, problems))

    for _ in range(n):
        add("ok", reference, "conforme", [])
    for _ in range(n):
        if patches:
            add(
                "object_outside",
                paste(reference, _pick(patches, rng), outside, rng, 0.25),
                "conforme",
                [],
            )
    for slot, polygon in station["element_slots"].items():
        add(f"missing_{slot}", erase_region(reference, polygon), "anomalie", [f"missing:{slot}"])
    for zone, mask in zones.items():
        for _ in range(n):
            if patches:
                add(
                    f"object_in_{zone}",
                    paste(reference, _pick(patches, rng), mask, rng),
                    "anomalie",
                    [f"@{zone}"],
                )
            if person is not None:
                add(
                    f"person_in_{zone}",
                    paste(reference, person, mask, rng, 0.8),
                    "anomalie",
                    [f"@{zone}"],
                )
    return out


def _pick(patches: list[Patch], rng: np.random.Generator) -> Patch:
    return patches[int(rng.integers(len(patches)))]


def write(variants: list[Variant], folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    labels = []
    for v in variants:
        cv2.imwrite(str(folder / f"{v.name}.png"), v.image)
        labels.append(
            {
                "file": f"{v.name}.png",
                "kind": v.kind,
                "expected": v.expected,
                "problems": v.problems,
            }
        )
    (folder / "labels.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", required=True, help="name of stations/<name>.yaml")
    parser.add_argument("--data-root", default="data", help="folder holding raw/ and processed/")
    parser.add_argument("--n", type=int, default=10, help="variants per random kind")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-person", action="store_true", help="skip person variants")
    parser.add_argument("--force", action="store_true", help="rebuild the reference image")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    data_root = Path(args.data_root).expanduser()
    station = load_station(args.station)
    reference = cv2.imread(str(prepare_reference(station, data_root, args.force)))
    folder = station_dir(station, data_root)
    cv2.imwrite(str(folder / "preview.png"), draw_regions(reference, station))

    # Foreign objects: the elements of the OTHER stations.
    foreign: list[Patch] = []
    sources = [reference]
    for other in sorted(p.stem for p in STATIONS_DIR.glob("*.yaml")):
        if other == args.station:
            continue
        other_station = load_station(other)
        try:
            other_ref = cv2.imread(str(prepare_reference(other_station, data_root)))
        except FileNotFoundError:
            continue
        foreign += slot_patches(other_ref, other_station)
        sources.append(other_ref)
    person = None if args.no_person else person_patch(sources)
    if person is None and not args.no_person:
        log.info("No person found in the references: no person variants")

    variants = generate(
        reference, station, np.random.default_rng(args.seed), args.n, foreign, person
    )
    write(variants, folder / "variants")
    kinds: dict[str, int] = {}
    for v in variants:
        kinds[v.kind] = kinds.get(v.kind, 0) + 1
    print(f"{len(variants)} variants written to {folder / 'variants'}")
    for kind, count in kinds.items():
        print(f"  {kind:<28} {count}")


if __name__ == "__main__":
    main()
