"""Measure the workstation analyzer on a labelled station dataset (e.g. presse_5S).

    python -m usecases.workstation.evaluate [--station presse_5s] [--data-root data]
        [--detector none|coco|yoloe] [--device cpu|cuda] [--no-slots] [--annotate]

The station file (``stations/<name>.yaml``) gives the dataset, the reference view(s) and
their boxes. The analyzer is configured like the platform (config.yaml) plus the station,
alignment ON and persistence 1 (one photo per check).

HONEST MEASURE (cross-validation): the conforming photos are split in ``--folds`` groups.
Each group is judged by an analyzer whose "normal" was learned on the OTHER groups only,
so a good photo is never judged by a model that has seen it. Anomalies are judged by the
analyzer learned on all conforming photos (they are never used to learn).

Printed results (the figures for the jury):
- DETECTION: anomalies raising an alert (a_verifier or anomalie), and for the RIGHT
  reason (station ``anomaly_types``: zone_object / zone_person -> something in
  red_zone; disorder -> something on the bench or a tool not in its place);
- FALSE ALARMS: conforming photos raising an alert;
- per anomaly type and per view, alignment failures, mean latency.

Written to ``<data-root>/processed/workstation/<station>/``: ``results.csv``,
``preview_<view>.png`` and, with ``--annotate``, each photo aligned on its reference
with the boxes and the verdict (``annotated/``).
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from usecases.workstation.model import ALIGNMENT_FAILED, View, ZoneWorkstationAnalyzer
from usecases.workstation.station import analyzer_params, labelled_photos, load_station
from visionhub.config import load_use_case_config
from visionhub.contracts import AnalysisResult, Decision, FrameMeta, Thresholds, UseCase
from visionhub.decision import decide


def build_analyzer(
    station: dict[str, Any],
    normal_images: list[str],
    overrides: dict[str, Any],
    slots: bool = True,
) -> tuple[ZoneWorkstationAnalyzer, Thresholds]:
    """The analyzer with the platform config + the station, and its thresholds."""
    config = load_use_case_config(UseCase.WORKSTATION)
    params = {k: v for k, v in config.params.items() if k not in ("station", "data_root")}
    params |= analyzer_params(station, normal_images)
    if not slots:
        params["views"] = [{**v, "element_slots": {}} for v in params["views"]]
    params |= {"align": True, "persistence_frames": 1}
    params |= {k: v for k, v in overrides.items() if v is not None}
    analyzer = ZoneWorkstationAnalyzer()
    analyzer.load(params)
    return analyzer, config.thresholds


def right_reason(result: AnalysisResult, anomaly_type: str, reasons: dict) -> bool:
    """Did the analyzer report a problem of the expected kind?

    ``reasons`` (station ``anomaly_types``) maps an anomaly type to the zone where it must
    be found; ``None`` means any problem outside those zones (bench, tool board)."""
    found = [f for f in result.details.missing + result.details.misplaced if f != ALIGNMENT_FAILED]
    zone = reasons.get(anomaly_type)
    if zone:  # an object or a person in that zone
        return any(f.endswith(f"@{zone}") for f in found)
    # disorder: something on the bench or a tool not in its place
    zones = {z for z in reasons.values() if z}
    return any(not any(f.endswith(f"@{z}") for z in zones) for f in found)


def judge(
    analyzer: ZoneWorkstationAnalyzer,
    thresholds: Thresholds,
    station: dict[str, Any],
    rows: list[dict[str, str]],
    annotate_dir: Path | None = None,
) -> list[dict[str, Any]]:
    results = []
    for i, row in enumerate(rows):
        image = cv2.imread(str(station["dataset_dir"] / row["filename"]))
        if image is None:
            raise FileNotFoundError(station["dataset_dir"] / row["filename"])
        start = time.perf_counter()
        meta = FrameMeta(frame_id=str(i), workstation_id="EVAL", camera_id="EVAL")
        result = analyzer.analyze(image, meta)
        latency_ms = (time.perf_counter() - start) * 1000
        decision = decide(result.score, thresholds)
        kind = row["kind"]
        expected = "conforme" if kind == "good" else "anomalie"
        reasons = station.get("anomaly_types") or {}
        flagged = decision != Decision.CONFORME
        failed = ALIGNMENT_FAILED in result.details.misplaced
        results.append(
            {
                "file": row["filename"],
                "type": kind,
                "expected": expected,
                "decision": decision.value,
                "score": round(result.score, 3),
                "correct": flagged == (expected == "anomalie"),
                "right_reason": flagged
                and expected == "anomalie"
                and right_reason(result, kind, reasons),
                "named_person": any(f.startswith("person@") for f in result.details.misplaced),
                "view": "-" if failed else analyzer.last_view,
                "alignment_failed": failed,
                "found": "; ".join(result.details.missing + result.details.misplaced),
                "latency_ms": round(latency_ms, 1),
            }
        )
        if annotate_dir is not None:
            _annotate(analyzer, image, result, decision, annotate_dir / row["filename"], expected)
    return results


def evaluate(
    station: dict[str, Any],
    overrides: dict[str, Any],
    folds: int = 5,
    slots: bool = True,
    annotate_dir: Path | None = None,
    seed: int = 0,
) -> tuple[list[dict[str, Any]], ZoneWorkstationAnalyzer]:
    """Cross-validated evaluation of the whole dataset (see the module docstring)."""
    rows = labelled_photos(station)
    goods = [r for r in rows if r["kind"] == "good"]
    anomalies = [r for r in rows if r["kind"] != "good"]
    folds = min(folds, len(goods))  # few conforming photos: leave-one-out

    def path(r: dict[str, str]) -> str:
        return str(station["dataset_dir"] / r["filename"])

    results: list[dict[str, Any]] = []
    order = np.random.default_rng(seed).permutation(len(goods))
    for fold in np.array_split(order, max(1, folds)) if folds > 1 else []:
        held_out = [goods[i] for i in fold]
        train = [path(g) for g in goods if g not in held_out]
        analyzer, thresholds = build_analyzer(station, train, overrides, slots)
        results += judge(analyzer, thresholds, station, held_out, annotate_dir)

    analyzer, thresholds = build_analyzer(station, [path(g) for g in goods], overrides, slots)
    if folds <= 1:  # no cross-validation: good photos judged by a model that saw them
        results += judge(analyzer, thresholds, station, goods, annotate_dir)
    results += judge(analyzer, thresholds, station, anomalies, annotate_dir)
    return results, analyzer


# ------------------------------------------------------------------ outputs


def draw_regions(image: np.ndarray, view: View) -> np.ndarray:
    """Copy of the image with the zones (red) and slots (cyan) of a view drawn."""
    out = image.copy()
    h, w = out.shape[:2]
    for regions, colour in ((view.zones, (0, 0, 255)), (view.slots, (255, 255, 0))):
        for name, polygon in regions.items():
            pts = (np.array(polygon) * [w - 1, h - 1]).astype(np.int32)
            cv2.polylines(out, [pts], True, colour, 1)
            cv2.putText(out, name, (int(pts[0][0]) + 2, int(pts[0][1]) + 10), 0, 0.33, colour, 1)
    return out


def _annotate(analyzer, image, result, decision, out: Path, expected: str) -> None:
    picked = analyzer._pick_view(image)
    shown = image.copy() if picked is None else draw_regions(picked[1].aligned, picked[0])
    h, w = shown.shape[:2]
    for obj in result.details.detected:
        b = obj.bbox
        p1, p2 = (int(b.x1 * w), int(b.y1 * h)), (int(b.x2 * w), int(b.y2 * h))
        cv2.rectangle(shown, p1, p2, (0, 165, 255), 2)
    colours = {"conforme": (0, 160, 0), "a_verifier": (0, 165, 255), "anomalie": (0, 0, 220)}
    found = ", ".join(result.details.missing + result.details.misplaced) or "-"
    banner = np.full((20, w, 3), colours[decision.value], np.uint8)
    text = f"{decision.value} {result.score:.2f} (expected {expected}) {found}"
    cv2.putText(banner, text[:90], (4, 14), 0, 0.38, (255, 255, 255), 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.vstack([banner, shown]))


def summary(rows: list[dict[str, Any]]) -> str:
    alerts = [r for r in rows if r["expected"] == "anomalie"]
    normal = [r for r in rows if r["expected"] == "conforme"]
    detected = sum(r["decision"] != "conforme" for r in alerts)
    reason = sum(r["right_reason"] for r in alerts)
    false_alarms = sum(r["decision"] != "conforme" for r in normal)
    latency = sum(r["latency_ms"] for r in rows) / max(len(rows), 1)
    lines = [
        f"Photos: {len(rows)}  (anomalies: {len(alerts)}, good: {len(normal)})",
        f"DETECTION    : {detected}/{len(alerts)} alerts raised ({_pct(detected, len(alerts))}),"
        f" right reason {reason}/{len(alerts)} ({_pct(reason, len(alerts))})",
        f"FALSE ALARMS : {false_alarms}/{len(normal)} good photos flagged"
        f" ({_pct(false_alarms, len(normal))})",
        f"Alignment failed: {sum(r['alignment_failed'] for r in rows)}"
        f"   Mean latency: {latency:.0f} ms",
        "",
        f"{'type':<24}{'view':>6}{'n':>5}{'correct':>9}{'right reason':>14}",
    ]
    for kind, view in sorted(dict.fromkeys((r["type"], r["view"]) for r in rows)):
        group = [r for r in rows if r["type"] == kind and r["view"] == view]
        ok = sum(r["correct"] for r in group)
        rr = "-" if kind == "good" else sum(r["right_reason"] for r in group)
        lines.append(f"{kind:<24}{view:>6}{len(group):>5}{ok:>9}{rr!s:>14}")
    return "\n".join(lines)


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.0f} %" if b else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--station", default="presse_5s")
    parser.add_argument("--data-root", default="data", help="folder holding raw/ and processed/")
    parser.add_argument("--detector", choices=["none", "coco", "yoloe"], help="override config")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--folds", type=int, default=5, help="cross-validation folds (1 = none)")
    parser.add_argument("--no-slots", action="store_true", help="ignore the tool slots")
    parser.add_argument("--annotate", action="store_true", help="write annotated photos")
    args = parser.parse_args()

    station = load_station(args.station, args.data_root)
    out_dir = station["data_root"] / "processed" / "workstation" / station["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, analyzer = evaluate(
        station,
        {"detector": args.detector, "device": args.device},
        args.folds,
        not args.no_slots,
        out_dir / "annotated" if args.annotate else None,
    )
    for view in analyzer.views:
        cv2.imwrite(str(out_dir / f"preview_{view.name}.png"), draw_regions(view.image, view))
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"Station {station['name']} - analyzer {analyzer.name}+{analyzer.detector.name}"
        f" - cross-validation{' - no slots' if args.no_slots else ''}"
    )
    print(summary(rows))
    print(f"\nDetails: {out_dir / 'results.csv'}")


if __name__ == "__main__":
    main()
