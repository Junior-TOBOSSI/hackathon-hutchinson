"""HOVIS demo scenario: start-of-shift workstation check, then part-by-part quality.

    python -m uvicorn demo.scenario:app --port 8000
    # then, in argos-ui/:  VITE_USE_MOCK=false npm run dev   ->  http://localhost:5173

A small server with the endpoints the argos-ui OPERATOR screen needs in live mode (same
approach as usecases/safety/notebooks/hovis_demo.py, the Safety live demo). Not part of
the platform API: it chains the three use cases for the pitch.

Scenario (one station, C3·P06):
1. WORKSTATION CHECK (no activity started yet): the photo of the station takes the place
   of the camera image. One photo every ``CHECK_PERIOD`` s (2), analysed by the real
   workstation analyzer (section ``machine_cell_variant``):
   anomaly_04 (bin in the passage) -> NOK, the same photo again -> NOK, good_04 -> OK:
   "Workstation validated, the activity can start". Done ONCE: never checked again.
2. QUALITY: one part photo every ``QUALITY_PERIOD`` s (2), classified by the real quality
   model (qualite702 v1). When a part is KO, the scenario WAITS for the operator's
   "Confirmer" (POST /api/stations/{id}/parts/confirm), then goes on.
   Photos: the model's VALIDATION bursts only (R08, R12, R14, R21, R26, R27), never used
   to train the weights.
3. SAFETY (optional): if the Safety weights are on this machine and a webcam is there,
   EPI's live analysis runs as in hovis_demo (Sécurité tile, camera image, faces hidden).

Production counters are the scenario's own (parts analysed since the activity started);
nothing else is simulated. Options (environment): CHECK_PERIOD, QUALITY_PERIOD,
VALIDATED_HOLD (s shown before the quality phase), SAFETY=0 to disable the webcam.
"""

from __future__ import annotations

import itertools
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, Response

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from usecases.quality.model702 import Quality702Analyzer  # noqa: E402
from usecases.workstation.evaluate import build_analyzer, shared_detector  # noqa: E402
from usecases.workstation.render import describe, render  # noqa: E402
from usecases.workstation.station import load_station, normal_photos  # noqa: E402
from visionhub.config import load_use_case_config  # noqa: E402
from visionhub.contracts import FrameMeta, UseCase  # noqa: E402
from visionhub.decision import decide  # noqa: E402

log = logging.getLogger("scenario")
STATION = "C3·P06"
DATA = REPO / "data"
CHECK_PERIOD = float(os.environ.get("CHECK_PERIOD", "2"))
QUALITY_PERIOD = float(os.environ.get("QUALITY_PERIOD", "2"))
VALIDATED_HOLD = float(os.environ.get("VALIDATED_HOLD", "3"))
SECTION = os.environ.get("WORKSTATION_SECTION", "machine_cell_variant")
CHECK_SEQUENCE = ["anomaly/anomaly_04.png", "anomaly/anomaly_04.png", "good/good_04.png"]
VAL_BURSTS = {"R08", "R12", "R14", "R21", "R26", "R27"}  # qualite702 v1 report
SAFETY_WEIGHTS = REPO / "data/models/safety/sh17_ours_yolov8s_640.pt"
PER_HOUR = int(3600 / QUALITY_PERIOD)  # demo pace: one part per QUALITY_PERIOD

lock = threading.Lock()
state: dict = {}


def _jpeg(image: np.ndarray, width: int = 640) -> bytes:
    h, w = image.shape[:2]
    small = cv2.resize(image, (width, int(width * h / w)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _display_part(image: np.ndarray) -> np.ndarray:
    """For the SCREEN only: the quality photos are tiny (126 x 86) and very dark. Local
    contrast (CLAHE on the lightness), a gamma of 0.5 and enlargement make the groove visible to the
    operator. The model always analyses the ORIGINAL photo."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(lab[..., 0])
    bright = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    gamma = (255 * (np.arange(256) / 255) ** 0.5).astype(np.uint8)  # lift the dark tones
    return cv2.resize(cv2.LUT(bright, gamma), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)


# ------------------------------------------------------------------ preparation


def prepare_check() -> list[dict]:
    """Analyse the 3 workstation photos once, with the real analyzer. The validated photo
    (good_04) is NOT used to learn what is normal: it is judged, not learned."""
    station = load_station(SECTION, DATA)
    judged = {str(station["dataset_dir"] / f) for f in CHECK_SEQUENCE}
    normal = [p for p in normal_photos(station) if p not in judged]
    analyzer, thresholds = build_analyzer(station, normal, {}, detector=shared_detector({}))
    steps = []
    for i, name in enumerate(CHECK_SEQUENCE):
        image = cv2.imread(str(station["dataset_dir"] / name))
        result = analyzer.analyze(
            image, FrameMeta(frame_id=name, workstation_id=STATION, camera_id="front")
        )
        decision = decide(result.score, thresholds)
        steps.append(
            {
                "name": name,
                "ok": decision.value == "conforme",
                "findings": describe(result),
                "jpeg": _jpeg(render(image, analyzer, result, decision)),
            }
        )
        log.info("Check %d %s -> %s %s", i + 1, name, decision.value, describe(result))
    return steps


def quality_photos() -> list[Path]:
    """Validation-burst photos, OK and NOK interleaved (3 OK then 1 NOK), fixed order."""
    files = sorted(
        (int(p.stem.split("_")[-1]), p) for p in (DATA / "raw/quality/702").glob("*/*.jpg")
    )
    burst, prev, chosen = 0, None, []
    for t, p in files:  # same rule as the kit: a pause > 3 s starts a new burst
        if prev is not None and (t - prev) / 1000 > 3:
            burst += 1
        prev = t
        if f"R{burst:02d}" in VAL_BURSTS:
            chosen.append(p)
    rng = np.random.default_rng(0)
    ok = [p for p in chosen if p.parent.name == "OK"]
    nok = [p for p in chosen if p.parent.name == "NOK"]
    rng.shuffle(ok)
    rng.shuffle(nok)
    order = []
    for i, p in enumerate(nok):
        order += ok[3 * i : 3 * i + 3] + [p]
    return order + ok[3 * len(nok) :]


def reset() -> None:
    """Back to the workstation check (the analysed photos of the check are kept)."""
    with lock:
        steps = state.get("steps", [])
        state.clear()
        state.update(
            steps=steps,
            phase="CHECK",
            started=False,  # the check starts when the operator screen first asks for /live
            step=0,
            phase_since=time.monotonic(),
            validated_at=None,
            part=None,
            part_jpeg=None,
            good=0,
            ko=0,
            awaiting=False,
            run_since=None,
        )


# ------------------------------------------------------------------ scenario loop


def loop(steps: list[dict], quality: Quality702Analyzer, thresholds, photos: list[Path]) -> None:
    order = itertools.cycle(photos)
    while True:
        time.sleep(0.1)
        now = time.monotonic()
        with lock:
            phase, since = state["phase"], state["phase_since"]
            if not state["started"]:
                continue
            if phase == "CHECK" and now - since >= CHECK_PERIOD:
                if steps[state["step"]]["ok"]:  # the OK photo was shown long enough
                    state.update(
                        phase="VALIDATED",
                        phase_since=now,
                        validated_at=datetime.now().astimezone().isoformat(),
                    )
                else:
                    state["step"] = (state["step"] + 1) % len(steps)
                    state["phase_since"] = now
                continue
            if phase == "VALIDATED" and now - since >= VALIDATED_HOLD:
                state.update(phase="RUNNING", phase_since=now, run_since=now)
                since = now - QUALITY_PERIOD  # first part at once
                phase = "RUNNING"
            if phase != "RUNNING" or state["awaiting"] or now - since < QUALITY_PERIOD:
                continue
        path = next(order)
        image = cv2.imread(str(path))
        result = quality.analyze(
            image, FrameMeta(frame_id=path.name, workstation_id=STATION, camera_id="part")
        )
        ko = decide(result.score, thresholds).value != "conforme"
        defect = quality.last["defect"]
        with lock:
            number = state["good"] + state["ko"] + 1  # part number in this activity
            state["good" if not ko else "ko"] += 1
            state.update(
                phase_since=time.monotonic(),
                awaiting=ko,
                part_jpeg=_jpeg(_display_part(image), 480),
                part={
                    "number": number,
                    "verdict": "KO" if ko else "OK",
                    "score": round(result.score, 3),
                    "jointsDetected": {"NOK_SANS": 0, "NOK_DOUBLE": 2}.get(defect, 1),
                    "defectLabel": quality.last["label"],
                    "file": path.name,
                    "takenAt": datetime.now().astimezone().isoformat(),
                },
            )


# ------------------------------------------------------------------ app

app = FastAPI(title="HOVIS demo scenario")
safety: dict = {"on": False}


@app.on_event("startup")
def _start() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    os.chdir(REPO)
    steps = prepare_check()
    config = load_use_case_config(UseCase.QUALITY)
    quality = Quality702Analyzer()
    quality.load({**config.params, "device": "cpu"})
    photos = quality_photos()
    log.info("Quality: %d validation photos", len(photos))
    state["steps"] = steps
    reset()
    threading.Thread(
        target=loop, args=(steps, quality, config.thresholds, photos), daemon=True
    ).start()
    if os.environ.get("SAFETY", "1") != "0" and SAFETY_WEIGHTS.exists():
        sys.path.insert(0, str(REPO / "usecases/safety/notebooks"))
        import hovis_demo  # EPI's live Safety demo: webcam + YOLO, faces hidden first

        threading.Thread(target=hovis_demo.loop, daemon=True).start()
        safety.update(on=True, module=hovis_demo)
        log.info("Safety: live webcam analysis on")
    else:
        log.info("Safety: off (no weights at %s or SAFETY=0); tile stays OK", SAFETY_WEIGHTS)


def _safety_issues() -> tuple[list, bool]:
    if not safety["on"]:
        return [], False
    mod = safety["module"]
    with mod.lock:
        return list(mod.state["issues"]), bool(mod.state["n"])


@app.post("/api/auth/login")
def login(body: dict) -> dict:
    return {"id": "demo", "name": "Opérateur démo", "role": "OPERATEUR", "stationId": STATION}


@app.get("/api/stations/{station_id}/live")
def live(station_id: str) -> dict:
    with lock:
        if not state["started"]:  # first look of the operator screen: the check begins
            state.update(started=True, phase_since=time.monotonic())
        s = {k: v for k, v in state.items() if k != "steps"}
        steps = state.get("steps", [])
    local = datetime.now().astimezone()
    now = local.isoformat()
    safety_issues, camera = _safety_issues()
    issues = list(safety_issues)
    step = steps[s["step"]] if steps else {"ok": True, "findings": []}
    if s["phase"] == "CHECK" and not step["ok"]:
        issues.append(
            {
                "id": "poste-check",
                "category": "POSTE",
                "label": "Poste non conforme",
                "instruction": "Dégagez le passage",
                "since": now,
            }
        )
    good, ko = s["good"], s["ko"]
    elapsed = (time.monotonic() - s["run_since"]) if s["run_since"] else 0.0
    part = s["part"] or {
        "number": 0,
        "verdict": "OK",
        "jointsDetected": 1,
        "score": 0.0,
        "takenAt": now,
    }
    return {
        "stationId": STATION,
        "product": "raccord 702 · démo",
        "shift": {"code": "B", "start": "13:00", "end": "21:00"},
        "now": now,
        "startup": {
            "phase": s["phase"],
            "step": s["step"] + 1,
            "steps": len(steps),
            "verdict": "OK" if step["ok"] else "KO",
            "findings": step["findings"],
            "imageUrl": f"/api/scenario/workstation.jpg?step={s['step']}",
            "validatedAt": s["validated_at"],
            "section": "Machine cell variant",
        },
        "part": {
            **{k: part[k] for k in ("number", "verdict", "jointsDetected", "score", "takenAt")},
            "imageUrl": f"/api/scenario/part.jpg?n={part['number']}"
            if s["part"]
            else "/img/demo-piece-ok.svg",
            "awaitingConfirmation": s["awaiting"],
            "defectLabel": part.get("defectLabel"),
        },
        "counters": {"good": good, "ko": ko},
        "objective": {
            "shiftTarget": 1000,
            "expectedNow": round(elapsed / QUALITY_PERIOD),
            "perHour": PER_HOUR,
        },
        "hourly": [{"hour": local.hour, "good": good}],
        "issues": issues,
        "frontSnapshotUrl": "/api/safety-demo/stream.mjpg" if camera else None,
        "checks": {
            "securite": not any(i["category"] != "POSTE" for i in issues),
            "poste": not any(i["category"] == "POSTE" for i in issues),
            "qualite": not s["awaiting"],
            "koRatePct": round(100 * ko / max(1, good + ko), 1),
        },
        "qualityModelVersion": "qualite702 v1",
        "partCameraOnline": True,
    }


@app.get("/api/scenario/workstation.jpg")
def workstation_jpg(step: int = 0) -> Response:
    steps = state.get("steps", [])
    jpeg = steps[step % len(steps)]["jpeg"] if steps else b""
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/scenario/part.jpg")
def part_jpg(n: int = 0) -> Response:
    with lock:
        jpeg = state.get("part_jpeg") or b""
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/stations/{station_id}/parts/confirm", status_code=204)
def confirm(station_id: str) -> Response:
    """The operator confirmed the KO part: the scenario goes on with the next part."""
    with lock:
        state.update(awaiting=False, phase_since=time.monotonic() - QUALITY_PERIOD)
    return Response(status_code=204)


@app.post("/api/scenario/restart", status_code=204)
def restart() -> Response:
    """Start the scenario again from the workstation check (for rehearsals)."""
    reset()
    return Response(status_code=204)


@app.get("/api/safety-demo/stream.mjpg")
def stream():
    if not safety["on"]:
        return Response(status_code=404)
    return safety["module"].stream()


@app.post("/api/stations/{station_id}/report", status_code=204)
def report(station_id: str) -> Response:
    return Response(status_code=204)


@app.get("/api/cells/{cell_id}/alerts")
def alerts(cell_id: str) -> list:
    return []


@app.get("/api/scenario/status")
def status() -> dict:
    with lock:
        return {k: v for k, v in state.items() if k not in ("steps", "part_jpeg")} | {
            "safety": safety["on"]
        }
