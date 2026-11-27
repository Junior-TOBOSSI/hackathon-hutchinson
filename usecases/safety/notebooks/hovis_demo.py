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
from datetime import UTC, datetime, timedelta
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
        if analyzer.last_camera_blocked:  # hand on the lens: nobody seen, the screen shows the part
            tracker.clear()
        issues = tracker.update(
            result,
            idle_phone=bool(analyzer.last_idle_phones),
            person_states=analyzer.last_states,  # shoes included
        )
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
            record_episodes(issues, datetime.now().astimezone())
            ppe = station_ppe(analyzer.last_states, issues)
            state.update(issues=issues, ppe=ppe, jpeg=jpeg, n=n, error=None, blocked=analyzer.last_camera_blocked,
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
    """Demo accounts: a login containing 'leader', 'manager' or 'chef' is the team leader."""
    who = str(body.get("login", "")).lower()
    if any(k in who for k in ("leader", "manager", "chef")):
        return {"id": "demo-tl", "name": "Team leader démo", "role": "TEAM_LEADER", "cellId": "C3"}
    return {"id": "demo", "name": "Opérateur démo", "role": "OPERATEUR", "stationId": STATION, "cellId": "C3"}


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
    if station_id != STATION:
        return simulated_station_live(station_id)
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
        "part": current_part(prod["good"] + prod["ko"] + 1, now),
        "counters": {"good": prod["good"], "ko": prod["ko"]},
        "objective": {"shiftTarget": prod["shiftTarget"], "expectedNow": prod["expectedNow"], "perHour": PER_HOUR},
        "hourly": prod["hourly"],  # SIMULATED
        "issues": issues,
        "safetyPpe": ppe,  # helmet/glasses/gloves/shoes: absent | present | uncertain
        "frontSnapshotUrl": "/api/safety-demo/stream.mjpg" if n else None,  # same URL: the stream stays open
        "checks": {**station_checks(issues), "qualite": PART["verdict"] == "OK", "koRatePct": round(100 * prod["ko"] / max(1, prod["good"] + prod["ko"]), 1)},
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


# SIMULATED quality (no quality model here): a NOK part can be triggered for the demo, and the
# operator can re-check it and requalify it OK (false alarm). In memory only.
# The NOK photo is served by argos-ui (public/img/piece-nok.jpg): an industrial image, NEVER committed.
PART = {"number": None, "verdict": "OK", "requalified": False}
REQUALIFIED: list[dict] = []  # trace of requalifications (part number, time), in memory


def current_part(number: int, now: str) -> dict:
    """The part on screen: a simulated OK part, or the NOK part of the demo until the next one.

    After a requalification, the photo stays the same: it is the same part.
    """
    if PART["number"] is not None and number > PART["number"] + 1:
        PART.update(number=None, verdict="OK", requalified=False)  # the next part has arrived
    ko = PART["verdict"] == "KO"
    photo = "/img/piece-nok.jpg" if ko or PART["requalified"] else "/img/demo-piece-ok.svg"
    return {
        "number": PART["number"] or number,
        "verdict": PART["verdict"],
        "jointsDetected": 2 if ko else 1,
        "score": 0.91 if ko else 0.96,
        "requalified": PART["requalified"],
        "imageUrl": photo,
        "takenAt": now,
    }


@app.post("/api/safety-demo/part-nok", status_code=204)
def part_nok() -> Response:
    """Demo: a NOK part (2 joints) arrives."""
    local = datetime.now().astimezone()
    prod = simulated_production(local, current_shift(local)[1])
    PART.update(number=prod["good"] + prod["ko"] + 1, verdict="KO", requalified=False)
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/{number}/requalify", status_code=204)
def requalify(station_id: str, number: int) -> Response:
    """The operator re-checked the NOK part: it is good (false alarm). Traced, never silent."""
    if PART["verdict"] == "KO":
        PART.update(verdict="OK", requalified=True)
        REQUALIFIED.append({"part": number, "at": datetime.now().astimezone().isoformat()})
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/report", status_code=204)
def report(station_id: str) -> Response:
    """The operator pressed 'Signaler un problème': the team leader gets an alert."""
    REPORTS.append({"id": f"report-{len(REPORTS) + 1}", "at": datetime.now().astimezone()})
    return Response(status_code=204)


# --------------------------------------------------------------------------- manager view
# The team leader sees the cell: station C3·P06 is REAL (camera, Safety alerts, requalified
# parts, operator reports); the 11 other stations are SIMULATED and labelled as such.
EVENTS: list[dict] = []  # Safety episodes of the real station: start, end, label, category
REPORTS: list[dict] = []  # 'Signaler un problème' pressed by the operator
ACK: dict[str, str] = {}  # alert id -> who took it in charge
DONE: set[str] = set()  # alerts closed by the team leader (decision, maintenance called)
CELL_STATIONS = [f"C3·P{i:02d}" for i in range(1, 13)]
DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
          "octobre", "novembre", "décembre"]  # fmt: skip


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def record_episodes(issues: list[dict], now: datetime) -> None:
    """Keep one episode per issue (start, end) for the station history."""
    current = {f"{i['id']}@{i['since']}": i for i in issues}
    for e in EVENTS:
        if e["end"] is None and e["key"] not in current:
            e["end"] = now
    known = {e["key"] for e in EVENTS}
    for key, i in current.items():
        if key not in known:
            EVENTS.append({"key": key, "start": now, "end": None, "label": i["label"], "category": i["category"]})


def context() -> tuple[datetime, dict, list[int], dict]:
    local = datetime.now().astimezone()
    shift, hours = current_shift(local)
    return local, shift, hours, simulated_production(local, hours)


def station_summary(sid: str, prod: dict, issues: list[dict]) -> dict:
    """One station of the cell: the real one, or a simulated one (reproducible, no random)."""
    if sid == STATION:
        cats = {i["category"] for i in issues}
        good, ko = prod["good"], prod["ko"]
        status = ("SECURITE" if cats & {"SECURITE_EPI", "COMPORTEMENT"} else "OBJET" if "POSTE" in cats
                  else "QUALITE" if PART["verdict"] == "KO" else "OK")  # fmt: skip
        return {"id": sid, "product": "raccord QC 702", "good": good, "target": prod["shiftTarget"],
                "expectedNow": prod["expectedNow"], "ko": ko, "status": status}  # fmt: skip
    i = int(sid[-2:])
    offset = (i * 37) % 23 - 9  # -9 .. +13 pieces around the plan
    good = max(0, prod["expectedNow"] + offset)
    return {"id": sid, "product": "raccord QC 702 · simulé", "good": good, "target": prod["shiftTarget"],
            "expectedNow": prod["expectedNow"], "ko": 2 + (i * 5) % 6,
            "status": "RYTHME" if offset < -6 else "OK"}  # fmt: skip


def simulated_station_live(sid: str) -> dict:
    """Screen of a simulated station (the team leader consults it): no camera, no issue."""
    local, shift, hours, prod = context()
    st = station_summary(sid, prod, [])
    now = local.isoformat()
    return {
        "stationId": sid, "product": st["product"], "shift": shift, "now": now,
        "part": {"number": st["good"] + st["ko"] + 1, "verdict": "OK", "jointsDetected": 1, "score": 0.96,
                 "imageUrl": "/img/demo-piece-ok.svg", "takenAt": now},
        "counters": {"good": st["good"], "ko": st["ko"]},
        "objective": {"shiftTarget": st["target"], "expectedNow": st["expectedNow"], "perHour": PER_HOUR},
        "hourly": prod["hourly"], "issues": [], "frontSnapshotUrl": None,
        "checks": {"securite": True, "poste": True, "qualite": True,
                   "koRatePct": round(100 * st["ko"] / max(1, st["good"] + st["ko"]), 1)},
        "qualityModelVersion": "simulé", "partCameraOnline": True,
    }  # fmt: skip


@app.get("/api/cells/{cell_id}/overview")
def cell_overview(cell_id: str) -> dict:
    local, shift, hours, prod = context()
    with lock:
        issues = list(state["issues"])
    stations = [station_summary(sid, prod, issues) for sid in CELL_STATIONS]
    n = len(CELL_STATIONS)
    hourly = [{"hour": h["hour"], "good": None if h["good"] is None else h["good"] * n,
               "ko": 0 if h["good"] is None else 3 * n // 2} for h in prod["hourly"]]  # fmt: skip
    return {
        "uap": {"id": "UAP2", "name": "UAP 2 · Injection"},
        "cell": {"id": cell_id, "name": "Cellule 3"},  # P06 real, the 11 others simulated
        "date": f"{DAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}",
        "currentShift": shift, "stations": stations, "hourly": hourly,
    }  # fmt: skip


@app.get("/api/cells/{cell_id}/alerts")
def alerts(cell_id: str) -> list:
    """Open alerts of the cell: Safety issues of the real station, reports, requalified parts."""
    local, shift, hours, prod = context()
    with lock:
        issues = list(state["issues"])
    out = []
    for i in issues:
        cat = "POSTE" if i["category"] == "POSTE" else "SECURITE_EPI"
        since = datetime.fromisoformat(i["since"]).astimezone()
        out.append({"id": i["id"], "cellId": cell_id, "stationId": STATION, "category": cat, "title": i["label"],
                    "detail": f"{i['instruction']} · vu par la caméra frontale (visage flouté)",
                    "shift": shift["code"], "when": f"depuis {hhmm(since)}", "priority": cat == "SECURITE_EPI",
                    "action": "NONE", "acknowledgedBy": ACK.get(i["id"])})  # fmt: skip
    for r in REPORTS:
        if r["id"] not in DONE:
            out.append({"id": r["id"], "cellId": cell_id, "stationId": STATION, "category": "EQUIPEMENT",
                        "title": "Problème signalé par l’opérateur",
                        "detail": "Bouton « Signaler un problème » sur l’écran du poste", "shift": shift["code"],
                        "when": hhmm(r["at"]), "priority": True, "action": "MAINTENANCE",
                        "reportedByOperator": True, "acknowledgedBy": ACK.get(r["id"])})  # fmt: skip
    for k, q in enumerate(REQUALIFIED):
        aid = f"requal-{k + 1}"
        if aid not in DONE:
            at = datetime.fromisoformat(q["at"])
            out.append({"id": aid, "cellId": cell_id, "stationId": STATION, "category": "QUALITE",
                        "title": f"Pièce n° {q['part']} requalifiée OK par l’opérateur",
                        "detail": "Le modèle qualité avait vu 2 joints : fausse alerte à confirmer",
                        "shift": shift["code"], "when": hhmm(at), "priority": False, "action": "VALIDATE",
                        "acknowledgedBy": ACK.get(aid)})  # fmt: skip
    return out


@app.post("/api/alerts/{alert_id}/acknowledge", status_code=204)
def acknowledge(alert_id: str) -> Response:
    ACK[alert_id] = "Team leader démo"
    return Response(status_code=204)


@app.post("/api/alerts/{alert_id}/decision", status_code=204)
def decide_alert(alert_id: str) -> Response:
    DONE.add(alert_id)
    return Response(status_code=204)


@app.post("/api/alerts/{alert_id}/maintenance", status_code=204)
def call_maintenance(alert_id: str) -> Response:
    DONE.add(alert_id)
    return Response(status_code=204)


EPI_LABELS = ["Casque absent", "Lunettes absentes", "Gants absents", "Chaussures de sécurité non détectées",
              "Téléphone en main", "Téléphone sur le poste"]  # fmt: skip


@app.get("/api/stations/{station_id}/detail")
def station_detail(station_id: str) -> dict:
    """Shift history of a station: real Safety episodes for C3·P06, simulated production."""
    local, shift, hours, prod = context()
    st = station_summary(station_id, prod, [])
    start_h = int(shift["start"][:2])
    shift_start = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
    if local.hour < start_h:  # shift C crosses midnight
        shift_start -= timedelta(days=1)
    real = station_id == STATION
    with lock:
        events = [dict(e) for e in EVENTS] if real else []

    def minutes(t: datetime) -> int:
        return max(0, int((t - shift_start).total_seconds() // 60))

    def lane(cats: set[str]) -> list[list[int]]:
        return [[minutes(e["start"]), max(minutes(e["start"]) + 1, minutes(e["end"] or local))]
                for e in events if e["category"] in cats]  # fmt: skip

    def detail(e: dict) -> str:
        if e["end"] is None:
            return "en cours"
        sec = int((e["end"] - e["start"]).total_seconds())
        return f"revenu au vert après {sec} s" if sec < 60 else f"revenu au vert après {sec // 60} min {sec % 60:02d}"

    category = {"SECURITE_EPI": "EPI", "COMPORTEMENT": "COMPORTEMENT", "POSTE": "POSTE"}
    elapsed_h = max(0.1, (local - shift_start).total_seconds() / 3600)
    return {
        "stationId": station_id, "product": f"Presse injection · {st['product']}",
        "efficiencyPct": round(100 * st["good"] / max(1, st["expectedNow"])), "good": st["good"],
        "expectedNow": st["expectedNow"], "delta": st["good"] - st["expectedNow"],
        "ratePerHour": round(st["good"] / elapsed_h), "ko": st["ko"],
        "koRatePct": round(100 * st["ko"] / max(1, st["good"] + st["ko"]), 1),
        "koByDefect": {"absent": st["ko"] // 2, "double": st["ko"] - st["ko"] // 2},
        "lanes": [
            {"name": "Sécurité", "episodes": lane({"SECURITE_EPI", "COMPORTEMENT"})},
            {"name": "Poste", "episodes": lane({"POSTE"})},
            {"name": "Qualité", "episodes": []},
            {"name": "Rythme", "episodes": [], "soft": True},
        ],
        "epiCounts": [{"label": lab, "count": sum(e["label"] == lab for e in events)} for lab in EPI_LABELS],
        "events": [{"time": hhmm(e["start"]), "category": category[e["category"]], "label": e["label"],
                    "detail": detail(e), "shift": shift["code"]} for e in reversed(events)][:50],
    }  # fmt: skip


@app.get("/api/safety-demo/status")
def status() -> dict:
    with lock:
        return {"frames": state["n"], "ms_per_frame": state.get("ms"), "camera_blocked": state.get("blocked"), "issues": state["issues"], "error": state["error"]}
