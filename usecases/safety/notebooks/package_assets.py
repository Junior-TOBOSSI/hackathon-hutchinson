"""Build the PRIVATE Safety package: model weights + prepared dataset, to share by a private channel.

NEVER commit or push what this script produces: the repository is public, and the package holds
model weights and photos of people (SH17, CC BY-NC-SA 4.0, non-commercial).

Run it where the weights and the dataset are (the school GPU server):
    python usecases/safety/notebooks/package_assets.py                 # images resized (default)
    python usecases/safety/notebooks/package_assets.py --images none   # weights + labels only
    python usecases/safety/notebooks/package_assets.py --images full   # original images (~13 GB)

Output, in data/exports/ (ignored by Git): a folder and its .tar.gz with
    models/                  every final Safety model (sh17_*_640.pt) + the COCO phone model
    dataset/sh17_ours/       data.yaml, train/val/test lists, labels and (by default) images
    SHA256SUMS               to check every file after the transfer (shasum -a 256 -c SHA256SUMS)
    README.txt               what is inside, licence, where it comes from
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tarfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "data/models"
DATASET = REPO / "data/processed/safety/sh17_ours"
PHONE_MODEL = MODELS / "yolov8n_coco.pt"

README = """HOVIS · cas Safety · paquet privé ({day})
NE PAS VERSIONNER, NE PAS PUBLIER : poids de modèles et photos de personnes.

models/   modèles EPI entraînés sur SH17 (9 classes : person, face, helmet, glasses, gloves,
          shoes, head, hands, foot) ; yolov8n_coco.pt = modèle téléphone (classe « cell phone »).
          Recommandé : sh17_ours_yolo26s_640.pt. Léger (Raspberry Pi) : sh17_ours_yolo26n_640.pt.
dataset/  SH17 préparé : découpage train/val/test fixe (graine 0), annotations YOLO,
          images {images}. Avant usage : mettre dans data.yaml « path: » = chemin de ce dossier.

Données : SH17 (Ahmad et Rahimi, 2024), licence CC BY-NC-SA 4.0, usage non commercial.
Vérifier après transfert : shasum -a 256 -c SHA256SUMS
Détails : usecases/safety/MODELS.md et usecases/safety/DATASET.md (branche safety-models).
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_images(src: Path, dst: Path, mode: str, max_side: int) -> int:
    """Copy the images of the prepared dataset (symlinks followed), resized or not."""
    if mode == "none":
        return 0
    import cv2  # installed with ultralytics

    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for image in sorted(src.iterdir()):
        if not image.is_file():
            continue
        target = dst / image.name
        if mode == "full":
            shutil.copyfile(image, target)  # follows the symlink to the original file
        else:
            pixels = cv2.imread(str(image))
            if pixels is None:
                continue
            h, w = pixels.shape[:2]
            scale = max_side / max(h, w)
            if scale < 1:  # never upscale; labels are normalized, so they stay valid
                pixels = cv2.resize(pixels, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(target), pixels, [cv2.IMWRITE_JPEG_QUALITY, 90])
        count += 1
    return count


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", choices=["resized", "full", "none"], default="resized")
    parser.add_argument("--max-side", type=int, default=1280, help="longest side of resized images")
    parser.add_argument("--out", type=Path, default=REPO / f"data/exports/safety_assets_{date.today():%Y%m%d}")
    args = parser.parse_args(argv)

    out: Path = args.out
    if out.exists():
        raise SystemExit(f"{out} already exists: remove it or pass --out")
    (out / "models").mkdir(parents=True)

    models = sorted((MODELS / "safety").glob("sh17_*_640.pt")) + [PHONE_MODEL]
    for model in models:
        if model.is_file():
            shutil.copyfile(model, out / "models" / model.name)
            print(f"modèle   {model.name}")

    data = out / "dataset/sh17_ours"
    data.mkdir(parents=True)
    for name in ("train.txt", "val.txt", "test.txt"):
        shutil.copyfile(DATASET / name, data / name)
    yaml = (DATASET / "data.yaml").read_text().splitlines()
    yaml = [("path: ." if line.startswith("path:") else line) for line in yaml]
    (data / "data.yaml").write_text("\n".join(yaml) + "\n")
    shutil.copytree(DATASET / "labels", data / "labels")
    n = copy_images(DATASET / "images", data / "images", args.images, args.max_side)
    print(f"dataset  {n} images ({args.images}), découpage train/val/test et annotations")

    label = {"resized": f"redimensionnées ({args.max_side} px max)", "full": "d'origine", "none": "non incluses"}
    (out / "README.txt").write_text(README.format(day=date.today(), images=label[args.images]))
    files = sorted(p for p in out.rglob("*") if p.is_file())
    sums = [f"{sha256(p)}  {p.relative_to(out)}" for p in files]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")

    archive = out.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(out, arcname=out.name)
    size = archive.stat().st_size / 1e6
    print(f"\nPaquet privé : {archive} ({size:.0f} Mo). À partager en privé, JAMAIS sur GitHub.")


if __name__ == "__main__":
    main()
