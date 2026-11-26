"""Run the workstation analyzer on the sample images and print the decision of each.

    python -m usecases.workstation.run_samples [--folder data/processed/workstation/synthetic]

Uses usecases/workstation/config.yaml (detector, zones, thresholds), with the reference
image of the folder. Each scenario image is shown ``persistence_frames`` times in a row
(as if it stayed in front of the camera), then the sequence is played frame by frame.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from usecases.workstation.model import ZoneWorkstationAnalyzer
from visionhub.config import load_use_case_config
from visionhub.contracts import FrameMeta, UseCase
from visionhub.decision import decide


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default="data/processed/workstation/synthetic")
    parser.add_argument("--device", default="cpu", help="cpu, or cuda on the cluster")
    args = parser.parse_args()
    folder = Path(args.folder).expanduser()
    config = load_use_case_config(UseCase.WORKSTATION)
    params = {**config.params, "reference_image": str((folder / "reference.png").resolve())}

    def fresh() -> ZoneWorkstationAnalyzer:
        analyzer = ZoneWorkstationAnalyzer()
        analyzer.load({**params, "device": args.device})
        return analyzer

    def show(i: int, name: str, analyzer: ZoneWorkstationAnalyzer, image) -> None:
        meta = FrameMeta(frame_id=f"{name}-{i}", workstation_id="WS-T", camera_id="CAM-T")
        result = analyzer.analyze(image, meta)
        d = result.details
        problems = d.missing + d.misplaced
        print(
            f"{name:<40} score={result.score:.2f}  {decide(result.score, config.thresholds):<10}"
            f"  {', '.join(problems) or '-'}"
        )

    print("== Scenarios (each image held for persistence_frames frames)")
    for path in sorted((folder / "scenarios").glob("*.png")):
        analyzer, image = fresh(), cv2.imread(str(path))
        for i in range(analyzer.persistence_frames - 1):
            analyzer.analyze(image, FrameMeta(frame_id=str(i), workstation_id="W", camera_id="C"))
        show(0, path.stem, analyzer, image)

    print("\n== Sequence (2 images per second)")
    analyzer = fresh()
    for i, path in enumerate(sorted((folder / "sequence").glob("*.png"))):
        show(i, f"t={i / 2:4.1f}s {path.name}", analyzer, cv2.imread(str(path)))


if __name__ == "__main__":
    main()
