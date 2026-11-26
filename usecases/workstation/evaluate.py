"""Measure the workstation analyzer on the generated variants of a station.

    python -m usecases.workstation.evaluate --station poste1 [--data-root data]
        [--detector none|coco|yoloe] [--device cpu|cuda] [--annotate]

The analyzer is configured like the platform (usecases/workstation/config.yaml), with the
station's reference, zones and slots, alignment ON and persistence 1 (one photo).

Printed results (the figures for the jury):
- DETECTION: on the photos that should raise an alert, how many do (decision a_verifier or
  anomalie), and how many for the RIGHT reason (the expected slot / zone);
- FALSE ALARMS: on the conforming photos, how many raise an alert;
- per kind of variant, alignment failures, mean latency.
``results.csv`` is written next to the variants; ``--annotate`` also writes each photo
with the zones, slots and found problems drawn (``annotated/``).
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import cv2

from usecases.workstation.make_variants import draw_regions, load_station, station_dir
from usecases.workstation.model import ALIGNMENT_FAILED, ZoneWorkstationAnalyzer
from visionhub.config import load_use_case_config
from visionhub.contracts import AnalysisResult, Decision, FrameMeta, Thresholds, UseCase
from visionhub.decision import decide


def analyzer_for(station: dict[str, Any], reference: Path, overrides: dict[str, Any]):
    """The analyzer with the platform config + this station, and its thresholds."""
    config = load_use_case_config(UseCase.WORKSTATION)
    params = {
        **config.params,
        "reference_image": str(reference.resolve()),
        "empty_zones": station["empty_zones"],
        "element_slots": station["element_slots"],
        "align": True,
        "persistence_frames": 1,
        **{k: v for k, v in overrides.items() if v is not None},
    }
    analyzer = ZoneWorkstationAnalyzer()
    analyzer.load(params)
    return analyzer, config.thresholds


def right_reason(result: AnalysisResult, problems: list[str]) -> bool:
    """Did the analyzer report the expected problem (slot or zone)?"""
    found = result.details.missing + result.details.misplaced
    for p in problems:
        if p.startswith("missing:") and p.split(":", 1)[1] not in found:
            return False
        if p.startswith("@") and not any(f.endswith(p) for f in found):
            return False
    return True


def evaluate(
    analyzer: ZoneWorkstationAnalyzer,
    thresholds: Thresholds,
    folder: Path,
    annotate_with: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    rows = []
    for i, label in enumerate(labels):
        image = cv2.imread(str(folder / label["file"]))
        start = time.perf_counter()
        result = analyzer.analyze(
            image, FrameMeta(frame_id=str(i), workstation_id="EVAL", camera_id="EVAL")
        )
        latency_ms = (time.perf_counter() - start) * 1000
        decision = decide(result.score, thresholds)
        flagged = decision != Decision.CONFORME
        rows.append(
            {
                "file": label["file"],
                "kind": label["kind"],
                "expected": label["expected"],
                "decision": decision.value,
                "score": round(result.score, 3),
                "correct": flagged == (label["expected"] == "anomalie"),
                "right_reason": flagged and right_reason(result, label["problems"]),
                "alignment_failed": ALIGNMENT_FAILED in result.details.misplaced,
                "found": "; ".join(result.details.missing + result.details.misplaced),
                "latency_ms": round(latency_ms, 1),
            }
        )
        if annotate_with is not None:
            _annotate(
                analyzer, image, result, decision, annotate_with, folder.parent / "annotated", label
            )
    return rows


def _annotate(analyzer, image, result, decision, station, out_dir: Path, label) -> None:
    """The reference-aligned photo with regions and found problems, for a human check."""
    from usecases.workstation.align import align_to_reference

    alignment = align_to_reference(image, analyzer.reference, min_inliers=analyzer.min_inliers)
    shown = draw_regions(alignment.aligned if alignment.ok else image, station)
    h, w = shown.shape[:2]
    for obj in result.details.detected:
        b = obj.bbox
        cv2.rectangle(
            shown, (int(b.x1 * w), int(b.y1 * h)), (int(b.x2 * w), int(b.y2 * h)), (0, 165, 255), 2
        )
    colour = {"conforme": (0, 160, 0), "a_verifier": (0, 165, 255), "anomalie": (0, 0, 220)}[
        decision.value
    ]
    text = f"{decision.value} {result.score:.2f} | expected {label['expected']} | " + (
        ", ".join(result.details.missing + result.details.misplaced) or "-"
    )
    cv2.rectangle(shown, (0, 0), (w, 22), colour, -1)
    cv2.putText(shown, text[:120], (5, 16), 0, 0.45, (255, 255, 255), 1)
    out_dir.mkdir(exist_ok=True)
    cv2.imwrite(str(out_dir / label["file"]), shown)


def summary(rows: list[dict[str, Any]]) -> str:
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    detected = sum(r["decision"] != "conforme" for r in alerts)
    reason = sum(r["right_reason"] for r in alerts)
    false_alarms = sum(r["decision"] != "conforme" for r in normal)
    lines = [
        f"Photos: {len(rows)}  (alerts expected: {len(alerts)}, conforming: {len(normal)})",
        f"DETECTION    : {detected}/{len(alerts)} alerts raised"
        f" ({_pct(detected, len(alerts))}), right reason {reason}/{len(alerts)}",
        f"FALSE ALARMS : {false_alarms}/{len(normal)} conforming photos flagged"
        f" ({_pct(false_alarms, len(normal))})",
        f"Alignment failed: {sum(r['alignment_failed'] for r in rows)}"
        f"   Mean latency: {sum(r['latency_ms'] for r in rows) / max(len(rows), 1):.0f} ms",
        "",
        f"{'kind':<28}{'n':>4}{'correct':>9}{'right reason':>14}",
    ]
    for kind in dict.fromkeys(r["kind"] for r in rows):
        group = [r for r in rows if r["kind"] == kind]
        ok = sum(r["correct"] for r in group)
        rr = sum(r["right_reason"] for r in group) if group[0]["expected"] == "anomalie" else "-"
        lines.append(f"{kind:<28}{len(group):>4}{ok:>9}{rr!s:>14}")
    return "\n".join(lines)


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f} %" if b else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--detector", choices=["none", "coco", "yoloe"], help="override config")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--annotate", action="store_true", help="write annotated photos")
    args = parser.parse_args()

    station = load_station(args.station)
    folder = station_dir(station, Path(args.data_root).expanduser())
    analyzer, thresholds = analyzer_for(
        station, folder / "reference.png", {"detector": args.detector, "device": args.device}
    )
    rows = evaluate(analyzer, thresholds, folder / "variants", station if args.annotate else None)
    with (folder / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Station {args.station} - analyzer {analyzer.name}+{analyzer.detector.name}")
    print(summary(rows))
    print(f"\nDetails: {folder / 'results.csv'}")


if __name__ == "__main__":
    main()
