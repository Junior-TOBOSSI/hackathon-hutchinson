"""Train the PPE detector from generic COCO weights on the prepared SH17 dataset (GPU).

Usage (from the repository root, after prepare_dataset.py, on the GPU machine):
    D=data/processed/safety
    # quick check that everything runs (1 epoch on 2% of the images):
    python usecases/safety/notebooks/train_detector.py --data $D/sh17_ours/data.yaml --smoke
    # A (17 classes) and B (our classes): SAME settings, only the dataset changes
    python usecases/safety/notebooks/train_detector.py --data $D/sh17_all/data.yaml
    python usecases/safety/notebooks/train_detector.py --data $D/sh17_ours/data.yaml
    # bigger model (if the Raspberry Pi has an AI accelerator):
    python usecases/safety/notebooks/train_detector.py --weights data/models/yolov8s_coco.pt

Choices (to defend):
- start from COCO (generic objects, never saw SH17): no risk of re-learning the same images
  that the official SH17 weights were already trained on;
- early stopping (--patience): training stops when the VALIDATION score stops improving,
  so the kept model is the best one on images it never trained on;
- the validation split is the SH17 one (1,620 images), never used for training.

Outputs: data/processed/safety/runs/<name>/ (curves, metrics) and
data/models/safety/<name>.pt (best weights). Nothing leaves the machine (telemetry off).
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO
from ultralytics.utils import SETTINGS

SETTINGS.update({"sync": False})  # no Ultralytics telemetry (AGENTS.md: nothing leaves)


def absolute_data_yaml(data: Path) -> Path:
    """Copy data.yaml with an absolute 'path', so the dataset works wherever it was copied."""
    content = yaml.safe_load(data.read_text(encoding="utf-8"))
    content["path"] = str(data.parent.resolve())
    resolved = data.parent / "data_abs.yaml"
    resolved.write_text(yaml.safe_dump(content, sort_keys=False))
    return resolved


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data", type=Path, default=Path("data/processed/safety/sh17_ours/data.yaml")
    )
    parser.add_argument(
        "--weights",
        default="data/models/yolov8n_coco.pt",
        help="COCO start; yolov8n by default: the model must run on a Raspberry Pi",
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--patience", type=int, default=20, help="early stopping, in epochs")
    parser.add_argument("--batch", type=int, default=-1, help="-1 = as much as the GPU fits")
    parser.add_argument("--device", default="0", help="0 = first NVIDIA GPU, mps, cpu")
    parser.add_argument("--workers", type=int, default=16, help="CPU processes loading images")
    parser.add_argument(
        "--cache",
        choices=["ram", "disk", "none"],
        default="ram",
        help="ram: decode + resize every image ONCE (SH17 images are ~4500 px wide)",
    )
    # AMP (half precision) gives nan losses with torch 2.0 + Ultralytics 8.4 on the school GPU:
    # full precision by default, --amp only on a machine where it was checked.
    parser.add_argument("--amp", action="store_true", help="half precision (faster, see above)")
    parser.add_argument("--name", default=None, help="default: <dataset>_<model>_<imgsz>")
    parser.add_argument("--smoke", action="store_true", help="1 epoch on 2%% of the data")
    args = parser.parse_args(argv)

    # e.g. sh17_ours_yolov8n_640: dataset + model + image size, so runs never overwrite.
    model_name = Path(args.weights).stem.split("_")[0]  # yolov8n_coco.pt -> yolov8n
    name = args.name or f"{args.data.parent.name}_{model_name}_{args.imgsz}"
    name += "_smoke" if args.smoke else ""
    runs = Path("data/processed/safety/runs").resolve()
    model = YOLO(args.weights)
    model.train(
        data=str(absolute_data_yaml(args.data)),
        imgsz=args.imgsz,
        epochs=1 if args.smoke else args.epochs,
        fraction=0.02 if args.smoke else 1.0,
        patience=args.patience,
        batch=8 if args.smoke else args.batch,
        device=args.device,
        workers=args.workers,
        cache=False if args.cache == "none" else args.cache,
        amp=args.amp,
        project=str(runs),
        name=name,
        exist_ok=True,
        seed=0,  # same result when re-run with the same settings
        plots=True,  # training curves: useful for the jury
    )

    best = runs / name / "weights" / "best.pt"
    target = Path("data/models/safety") / f"{name}.pt"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, target)
    print(f"\nBest weights (chosen on validation) copied to {target}")
    print("Next: python usecases/safety/notebooks/evaluate_model.py "
          f"--weights {target} --dataset {args.data.parent} --n 1620")  # fmt: skip


if __name__ == "__main__":
    main()
