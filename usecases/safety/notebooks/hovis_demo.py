"""Local demo: real Safety model on the webcam -> HOVIS operator screen (argos-ui).

Not part of the platform: a small server with the few endpoints the argos-ui Operator page
needs in live mode, to test the Safety model end to end on a laptop.
- issues and the Sécurité / Poste tiles come from the REAL webcam + YoloSafetyAnalyzer +
  usecases/safety/hovis.py;
- the camera image is an MJPEG stream of analysed frames only, faces pixelated first
  (``last_privacy``, from conf 0.10); frames live in memory only, nothing is saved;
- production fields (part, counters, objective) are SIMULATED and labelled as such: there
  is no Production Engine on this machine.

Run, from the repo root (webcam access needed):
    YOLO_OFFLINE=1 uvicorn hovis_demo:app --port 8000 --app-dir usecases/safety/notebooks
then argos-ui (branch ``interface``) with ``VITE_USE_MOCK=false npx vite``. The video is a
stream, fluid whatever the page refresh (argos-ui keeps 2 s, on purpose, against blinking).
Options (environment): CAMERA (0), WEIGHTS, FPS (analyses per second, 4).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO), str(Path(__file__).parent)]

from usecases.safety.hovis import StationIssueTracker, station_checks, station_ppe  # noqa: E402
from usecases.safety.yolo_analyzer import YoloSafetyAnalyzer  # noqa: E402
from visionhub.contracts import FrameMeta  # noqa: E402
from webcam_preview import draw, hide_faces  # noqa: E402

STATION = "C3·P06"
CAMERA = int(os.environ.get("CAMERA", "0"))
WEIGHTS = os.environ.get("WEIGHTS", "data/models/safety/sh17_ours_yolov8s_640.pt")
PERIOD = 1 / float(os.environ.get("FPS", "4"))  # analyses per second

state = {"issues": [], "ppe": {}, "jpeg": None, "n": 0, "error": None}
lock = threading.Lock()


latest = {"frame": None}


def reader(cap) -> None:
    """Read the camera continuously and keep only the newest frame (no stale buffer)."""
    while True:
        ok, frame = cap.read()
        if ok:
            latest["frame"] = frame
        else:
            time.sleep(0.05)


def loop() -> None:
    analyzer = YoloSafetyAnalyzer()
    analyzer.load({"weights": WEIGHTS, "phone_weights": "data/models/yolov8n_coco.pt", "device": "cpu"})
    tracker = StationIssueTracker(STATION)
    cap = cv2.VideoCapture(CAMERA)
    threading.Thread(target=reader, args=(cap,), daemon=True).start()
    n = 0
    while True:
        start = time.perf_counter()
        frame = latest["frame"]
        if frame is None:
            time.sleep(0.05)
            continue
        frame = frame.copy()
        meta = FrameMeta(frame_id=f"demo-{n}", workstation_id=STATION, camera_id="front")
        result = analyzer.analyze(frame, meta)
        issues = tracker.update(result, idle_phone=bool(analyzer.last_idle_phones))
        # Snapshot: reuse the analyzer's detections (no second inference); faces hidden FIRST.
        h, w = frame.shape[:2]
        def px(d):
            return (d.name, d.conf, (int(d.box[0] * w), int(d.box[1] * h), int(d.box[2] * w), int(d.box[3] * h)))
        dets = [px(d) for d in analyzer.last_detections]
        hide_faces(frame, [px(d) for d in analyzer.last_privacy])  # from conf 0.10, not 0.25
        draw(frame, dets, 0.25)
        idle = {id(d) for d in analyzer.last_idle_phones}
        for d in analyzer.last_phones:
            _, conf, (x1, y1, x2, y2) = px(d)
            color, text = ((0, 165, 255), "phone sur le poste") if id(d) in idle else ((0, 0, 255), "phone en main")
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            cv2.putText(frame, f"{text} {conf:.2f}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        small = cv2.resize(frame, (640, int(640 * h / w)))
        jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes()
        n += 1
        with lock:
            ppe = station_ppe(analyzer.last_states, issues)
            state.update(issues=issues, ppe=ppe, jpeg=jpeg, n=n, error=None,
                         ms=round((time.perf_counter() - start) * 1000))
        time.sleep(max(0.0, PERIOD - (time.perf_counter() - start)))


SHIFTS = [("A", 5, 13), ("B", 13, 21), ("C", 21, 5)]  # 3x8, local time


def current_shift(now: datetime) -> tuple[dict, list[int]]:
    """Shift containing the local time, and its hours in order (C crosses midnight)."""
    h = now.hour
    for code, start, end in SHIFTS:
        inside = start <= h < end if start < end else (h >= start or h < end)
        if inside:
            hours = [(start + i) % 24 for i in range((end - start) % 24)]
            return {"code": code, "start": f"{start:02d}:00", "end": f"{end:02d}:00"}, hours
    raise AssertionError("every hour belongs to a shift")


app = FastAPI()


@app.on_event("startup")
def _start() -> None:
    os.chdir(REPO)
    threading.Thread(target=loop, daemon=True).start()


@app.post("/api/auth/login")
def login(body: dict) -> dict:
    return {"id": "demo", "name": "Opérateur démo", "role": "OPERATEUR", "stationId": STATION}


PER_HOUR = 125  # demo objective: 1 000 parts per 8-hour shift


def simulated_production(local: datetime, hours: list[int]) -> dict:
    """SIMULATED production (no Production Engine here): ~96 % of the hourly objective,
    reproducible (no random), only for elapsed hours; future hours stay empty."""
    idx = hours.index(local.hour)
    elapsed = idx + local.minute / 60
    hourly = []
    for i, h in enumerate(hours):
        if i < idx:
            good = PER_HOUR - (3 + (h * 7) % 6)  # 117-122 per full hour
        elif i == idx:
            good = int((PER_HOUR - 5) * local.minute / 60)
        else:
            good = None  # hour to come
        hourly.append({"hour": h, "good": good})
    good = sum(x["good"] or 0 for x in hourly)
    ko = max(1, round(good * 0.012))
    return {"hourly": hourly, "good": good, "ko": ko,
            "expectedNow": round(PER_HOUR * elapsed), "shiftTarget": PER_HOUR * len(hours)}


@app.get("/api/stations/{station_id}/live")
def live(station_id: str) -> dict:
    with lock:
        issues, ppe, n = list(state["issues"]), dict(state["ppe"]), state["n"]
    local = datetime.now().astimezone()  # the station's local time
    now = local.isoformat()
    shift, hours = current_shift(local)
    prod = simulated_production(local, hours)
    return {
        "stationId": STATION,
        "product": "DÉMO SAFETY · production simulée",
        "shift": shift,
        "now": now,
        "part": {"number": prod["good"] + prod["ko"] + 1, "verdict": "OK", "jointsDetected": 1, "score": 0.96,
                 "imageUrl": "/img/demo-piece-ok.svg", "takenAt": now},
        "counters": {"good": prod["good"], "ko": prod["ko"]},
        "objective": {"shiftTarget": prod["shiftTarget"], "expectedNow": prod["expectedNow"], "perHour": PER_HOUR},
        "hourly": prod["hourly"],  # SIMULATED
        "issues": issues,
        "safetyPpe": ppe,  # helmet/glasses/gloves/shoes: absent | present | uncertain
        "frontSnapshotUrl": "/api/safety-demo/stream.mjpg" if n else None,  # same URL: the stream stays open
        "checks": {**station_checks(issues), "qualite": True, "koRatePct": round(100 * prod["ko"] / max(1, prod["good"] + prod["ko"]), 1)},
        "qualityModelVersion": "simulé",
        "partCameraOnline": True,
    }


@app.get("/api/safety-demo/snapshot.jpg")
def snapshot(n: int = 0) -> Response:
    with lock:
        jpeg = state["jpeg"]
    return Response(jpeg or b"", media_type="image/jpeg", headers={"Cache-Control": "no-store"})


def mjpeg():
    """MJPEG: push each ANALYSED frame (faces already hidden) as soon as it is ready.
    Only analysed frames are sent: a raw camera frame could show a face."""
    last = -1
    while True:
        with lock:
            n, jpeg = state["n"], state["jpeg"]
        if n != last and jpeg:
            last = n
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.02)


@app.get("/api/safety-demo/stream.mjpg")
def stream() -> StreamingResponse:
    return StreamingResponse(mjpeg(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store"})


@app.post("/api/stations/{station_id}/report", status_code=204)
def report(station_id: str) -> Response:
    return Response(status_code=204)


@app.get("/api/cells/{cell_id}/alerts")
def alerts(cell_id: str) -> list:
    return []


@app.get("/api/safety-demo/status")
def status() -> dict:
    with lock:
        return {"frames": state["n"], "ms_per_frame": state.get("ms"), "issues": state["issues"], "error": state["error"]}
