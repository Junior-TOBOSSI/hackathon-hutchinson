"""HOVIS demo scenario: start-of-shift workstation check, then part-by-part quality.

    python -m uvicorn demo.scenario:app --port 8000
    # then, in argos-ui/:  VITE_USE_MOCK=false npm run dev   ->  http://localhost:5173

A small server with the endpoints the argos-ui screens need in live mode, built on EPI's
Safety demo (usecases/safety/notebooks/hovis_demo.py): its shift logic, simulated
production of the other stations, alerts ("Prendre en charge") and team leader routes are
reused as they are. Not part of the platform API: it chains the use cases for the pitch.

Scenario (the real station C3·P06):
0. IDLE until the HOVIS logo of the operator screen is clicked (nothing shows it is a
   button): POST /api/scenario/restart starts (or restarts) the simulation.
1. WORKSTATION CHECK (no activity started yet): the photo of the station takes the place
   of the part, one photo every ``CHECK_PERIOD`` s (2.5), real workstation analyzer
   (section ``machine_cell_variant``): anomaly_04 (bin in the passage) -> KO, the same
   photo again -> KO, good_04 -> OK, "workstation validated". Done ONCE.
2. QUALITY: one part photo every ``QUALITY_PERIOD`` s (2), real quality model
   (qualite702 v1), validation-burst photos only (R08, R12, R14, R21, R26, R27).
   ``QUALITY_PATTERN`` "9:1": 9 good parts then 1 KO, repeated (a defect every 10 parts).
   A KO part WAITS for the operator: CONFIRMER (KO kept) or LAISSER PASSER (model error:
   the part counts as good, the team leader gets an alert to confirm).
3. SAFETY: if EPI's weights and a webcam are there, EPI's live analysis runs.

Supervisor (team leader, cell C3): 6 stations C3·P01..P06. P06 is the scenario station
(real verdicts, real alerts); the 5 others are simulated by EPI's code.

Counters of P06: the shift's production so far (EPI's simulation, ~96 % of the plan at
125 parts/h) frozen when the activity starts, plus the parts of the scenario. The plan
then advances at the demo pace ONLY while the line produces (not while a KO waits for the
operator): the delay moves only when production really stops.
"""

from __future__ import annotations

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
sys.path[:0] = [str(REPO), str(REPO / "usecases/safety/notebooks")]

import hovis_demo as epi  # noqa: E402  EPI's demo: shift, simulated stations, alerts

from usecases.quality.model702 import Quality702Analyzer  # noqa: E402
from usecases.workstation.evaluate import build_analyzer, shared_detector  # noqa: E402
from usecases.workstation.render import describe, render  # noqa: E402
from usecases.workstation.station import load_station, normal_photos  # noqa: E402
from visionhub.config import load_use_case_config  # noqa: E402
from visionhub.contracts import FrameMeta, UseCase  # noqa: E402
from visionhub.decision import decide  # noqa: E402

log = logging.getLogger("scenario")
STATION = epi.STATION  # "C3·P06"
CELL = [f"C3·P{i:02d}" for i in range(1, 7)]  # the team leader's 6 stations
epi.CELL_STATIONS = CELL  # EPI's cell routes now see 6 stations
DATA = REPO / "data"
CHECK_PERIOD = float(os.environ.get("CHECK_PERIOD", "2.5"))
QUALITY_PERIOD = float(os.environ.get("QUALITY_PERIOD", "2"))
VALIDATED_HOLD = float(os.environ.get("VALIDATED_HOLD", "3"))
SECTION = os.environ.get("WORKSTATION_SECTION", "machine_cell_variant")
CHECK_SEQUENCE = ["anomaly/anomaly_04.png", "anomaly/anomaly_04.png", "good/good_04.png"]
# "OK count:KO count" blocks, REPEATED: "9:1" = a defect every 10 parts.
QUALITY_PATTERN = os.environ.get("QUALITY_PATTERN", "9:1")
VAL_BURSTS = {"R08", "R12", "R14", "R21", "R26", "R27"}  # qualite702 v1 report

lock = threading.Lock()
state: dict = {"run": 0}


def _jpeg(image: np.ndarray, width: int = 640) -> bytes:
    h, w = image.shape[:2]
    small = cv2.resize(image, (width, int(width * h / w)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _display_part(image: np.ndarray) -> np.ndarray:
    """For the SCREEN only: the quality photos are tiny (126 x 86) and very dark. Local
    contrast (CLAHE on the lightness), a gamma of 0.5 and enlargement make the groove
    visible to the operator. The model always analyses the ORIGINAL photo."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(lab[..., 0])
    bright = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    gamma = (255 * (np.arange(256) / 255) ** 0.5).astype(np.uint8)  # lift the dark tones
    return cv2.resize(cv2.LUT(bright, gamma), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)


def _hhmm(t: datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


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
        meta = FrameMeta(frame_id=name, workstation_id=STATION, camera_id="front")
        result = analyzer.analyze(image, meta)
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


def quality_photos() -> tuple[list[Path], list[Path]]:
    """Validation-burst photos, (good parts, KO parts), fixed order (seed 0)."""
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
    return ok, nok


def pattern() -> list[bool]:
    """One period of QUALITY_PATTERN: True = KO part. "9:1" -> 9 False then 1 True."""
    out: list[bool] = []
    for block in QUALITY_PATTERN.split(","):
        n_ok, n_ko = (int(v) for v in block.split(":"))
        out += [False] * n_ok + [True] * n_ko
    return out


def photo_at(index: int, ok: list[Path], nok: list[Path]) -> Path:
    """Photo of the part n° index + 1, following the repeated pattern."""
    period = pattern()
    if not period[index % len(period)]:
        n = sum(not k for k in period[: index % len(period)]) + index // len(period) * period.count(
            False
        )
        return ok[n % len(ok)]
    n = sum(period[: index % len(period)]) + index // len(period) * period.count(True)
    return nok[n % len(nok)]


def reset() -> None:
    """Back to IDLE (the analysed photos of the check are kept)."""
    with lock:
        steps, run = state.get("steps", []), state.get("run", 0) + 1
        state.clear()
        state.update(
            steps=steps,
            run=run,  # alert ids of a new run never collide with an old one
            phase="IDLE",  # waits for a click on the HOVIS logo (POST /api/scenario/restart)
            step=0,
            phase_since=time.monotonic(),
            validated_at=None,
            part=None,
            part_jpeg=None,
            good=0,
            ko=0,
            awaiting=False,
            waiting_since=None,
            model_errors=0,  # KO parts released by the operator ("erreur modèle")
            active_s=0.0,  # seconds of production (KO waiting time excluded)
            base=None,  # shift production frozen when the activity starts
            events=[],  # quality KO of this run: part, time, released or not
            check_alert_since=None,
        )


# ------------------------------------------------------------------ scenario loop


def loop(steps: list[dict], quality: Quality702Analyzer, thresholds, photos) -> None:
    ok_photos, nok_photos = photos
    last = time.monotonic()
    while True:
        time.sleep(0.1)
        now = time.monotonic()
        tick, last = now - last, now
        with lock:
            phase, since = state["phase"], state["phase_since"]
            if phase == "IDLE":
                continue
            if phase == "CHECK" and now - since >= CHECK_PERIOD:
                if steps[state["step"]]["ok"]:  # the OK photo was shown long enough
                    stamp = datetime.now().astimezone().isoformat()
                    state.update(phase="VALIDATED", phase_since=now, validated_at=stamp)
                else:
                    state["step"] = (state["step"] + 1) % len(steps)
                    state["phase_since"] = now
                continue
            if phase == "VALIDATED" and now - since >= VALIDATED_HOLD:
                _, _, _, prod = epi.context()  # the shift so far, frozen at the start
                state.update(phase="RUNNING", phase_since=now, base=prod)
                since = now - QUALITY_PERIOD  # first part at once
                phase = "RUNNING"
            if phase != "RUNNING":
                continue
            if not state["awaiting"]:
                state["active_s"] += tick  # the plan advances only while producing
            if state["awaiting"] or now - since < QUALITY_PERIOD:
                continue
            index = state["good"] + state["ko"]  # parts already made in this activity
        path = photo_at(index, ok_photos, nok_photos)
        image = cv2.imread(str(path))
        meta = FrameMeta(frame_id=path.name, workstation_id=STATION, camera_id="part")
        result = quality.analyze(image, meta)
        ko = decide(result.score, thresholds).value != "conforme"
        defect = quality.last["defect"]
        with lock:
            number = state["good"] + state["ko"] + 1  # part number in this activity
            state["good" if not ko else "ko"] += 1
            at = datetime.now().astimezone()
            if ko:
                state["events"].append({"part": number, "at": at, "released": False})
            state.update(
                phase_since=time.monotonic(),
                awaiting=ko,
                waiting_since=at if ko else None,
                part_jpeg=_jpeg(_display_part(image), 480),
                part={
                    "number": number,
                    "verdict": "KO" if ko else "OK",
                    "score": round(result.score, 3),
                    "jointsDetected": {"NOK_SANS": 0, "NOK_DOUBLE": 2}.get(defect, 1),
                    "defectLabel": quality.last["label"],
                    "file": path.name,
                    "takenAt": at.isoformat(),
                },
            )


# ------------------------------------------------------------------ the scenario station


def production(s: dict) -> dict:
    """Counters, plan and hourly bars of C3·P06 (see the module docstring)."""
    local, shift, hours, prod = epi.context()
    base = s["base"] or prod  # before the activity: the shift as simulated by EPI
    demo_plan = int(s["active_s"] / QUALITY_PERIOD)
    hourly = [dict(h) for h in base["hourly"]]
    for h in hourly:
        if h["hour"] == local.hour:
            h["good"] = (h["good"] or 0) + s["good"]
    return {
        "shift": shift,
        "good": base["good"] + s["good"],
        "ko": base["ko"] + s["ko"],
        "expectedNow": base["expectedNow"] + demo_plan,
        "shiftTarget": base["shiftTarget"],
        "hourly": hourly,
    }


def check_issue(s: dict, now: str) -> list[dict]:
    """The workstation check in progress and not conforming: one POSTE issue."""
    steps = s.get("steps") or state.get("steps", [])
    if s["phase"] == "CHECK" and steps and not steps[s["step"]]["ok"]:
        return [
            {
                "id": f"poste-check-{s['run']}",
                "category": "POSTE",
                "label": "Poste non conforme",
                "instruction": "Dégagez le passage",
                "since": now,
            }
        ]
    return []


def safety_issues() -> tuple[list, bool]:
    if not safety["on"]:
        return [], False
    with epi.lock:
        return list(epi.state["issues"]), bool(epi.state["n"])


def snapshot() -> dict:
    with lock:
        return {k: v for k, v in state.items() if k not in ("steps", "part_jpeg")}


def summary(s: dict, issues: list[dict]) -> dict:
    """C3·P06 as a team leader station card."""
    p = production(s)
    cats = {i["category"] for i in issues}
    status = (
        "SECURITE" if cats & {"SECURITE_EPI", "COMPORTEMENT"}
        else "OBJET" if "POSTE" in cats
        else "QUALITE" if s["awaiting"]
        else "OK"
    )  # fmt: skip
    return {"id": STATION, "product": "raccord QC 702", "good": p["good"],
            "target": p["shiftTarget"], "expectedNow": p["expectedNow"], "ko": p["ko"],
            "status": status}  # fmt: skip


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
    log.info(
        "Quality: %d good and %d KO validation photos, pattern %s",
        *map(len, photos),
        QUALITY_PATTERN,
    )
    state["steps"] = steps
    reset()
    args = (steps, quality, config.thresholds, photos)
    threading.Thread(target=loop, args=args, daemon=True).start()
    weights = REPO / epi.WEIGHTS
    if os.environ.get("SAFETY", "1") != "0" and weights.exists():
        threading.Thread(target=epi.loop, daemon=True).start()  # webcam + YOLO, faces hidden
        safety["on"] = True
        log.info("Safety: EPI live webcam analysis on (%s)", weights.name)
    else:
        log.info("Safety: off (no weights at %s or SAFETY=0); tile stays OK", weights)


@app.post("/api/auth/login")
def login(body: dict) -> dict:
    """Demo accounts: a team leader login (c.diaz…, or containing leader / manager / chef)
    opens the team leader view of cell C3; anything else is the operator of C3·P06."""
    who = str(body.get("login", "")).lower()
    if who.startswith("c.diaz") or any(k in who for k in ("leader", "manager", "chef")):
        return {"id": "demo-tl", "name": "Team leader démo", "role": "TEAM_LEADER", "cellId": "C3"}
    return {
        "id": "demo",
        "name": "Opérateur démo",
        "role": "OPERATEUR",
        "stationId": STATION,
        "cellId": "C3",
    }


@app.get("/api/stations/{station_id}/live")
def live(station_id: str) -> dict:
    if station_id != STATION:  # a simulated station, consulted by the team leader
        return epi.simulated_station_live(station_id)
    s = snapshot()
    local = datetime.now().astimezone()
    now = local.isoformat()
    safety_list, camera = safety_issues()
    issues = safety_list + check_issue(s, now)
    steps = state.get("steps", [])
    step = steps[s["step"]] if steps else {"ok": True, "findings": []}
    p = production(s)
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
        "shift": p["shift"],
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
            if s["part"] else "/img/demo-piece-ok.svg",
            "awaitingConfirmation": s["awaiting"],
        },
        "counters": {"good": p["good"], "ko": p["ko"]},
        "objective": {"shiftTarget": p["shiftTarget"], "expectedNow": p["expectedNow"],
                      "perHour": epi.PER_HOUR},
        "hourly": p["hourly"],
        "issues": issues,
        "frontSnapshotUrl": "/api/safety-demo/stream.mjpg" if camera else None,
        "checks": {
            "securite": not any(i["category"] != "POSTE" for i in issues),
            "poste": not any(i["category"] == "POSTE" for i in issues),
            "qualite": not s["awaiting"],
            "koRatePct": round(100 * p["ko"] / max(1, p["good"] + p["ko"]), 1),
        },
        "qualityModelVersion": "qualite702 v1",
        "partCameraOnline": True,
    }  # fmt: skip


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
        state.update(
            awaiting=False, waiting_since=None, phase_since=time.monotonic() - QUALITY_PERIOD
        )
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/release", status_code=204)
def release(station_id: str) -> Response:
    """The operator disputes the KO ("erreur modèle"): the part goes on as GOOD, the model
    error is counted and the team leader gets an alert to confirm it."""
    with lock:
        if state["awaiting"]:
            state["ko"] -= 1
            state["good"] += 1
            state["model_errors"] += 1
            if state["part"]:
                state["part"]["verdict"] = "OK"
            if state["events"]:
                state["events"][-1]["released"] = True
        state.update(
            awaiting=False, waiting_since=None, phase_since=time.monotonic() - QUALITY_PERIOD
        )
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/{number}/requalify", status_code=204)
def requalify(station_id: str, number: int) -> Response:
    """EPI's 'Revérifier la pièce': same effect as LAISSER PASSER in this scenario."""
    return release(station_id)


@app.post("/api/scenario/restart", status_code=204)
def restart() -> Response:
    """Start (or restart) the simulation: the workstation check begins now."""
    reset()
    with lock:
        state.update(phase="CHECK", phase_since=time.monotonic())
    return Response(status_code=204)


# ------------------------------------------------------------------ team leader (cell C3)


@app.get("/api/cells/{cell_id}/overview")
def cell_overview(cell_id: str) -> dict:
    """EPI's cell view with 6 stations; C3·P06 comes from the scenario."""
    local, shift, hours, prod = epi.context()
    s = snapshot()
    safety_list, _ = safety_issues()
    mine = summary(s, safety_list + check_issue(s, local.isoformat()))
    others = [epi.station_summary(sid, prod, []) for sid in CELL if sid != STATION]
    p = production(s)
    n = len(others)
    hourly = []
    for i, h in enumerate(prod["hourly"]):
        if h["good"] is None:
            hourly.append({"hour": h["hour"], "good": None, "ko": 0})
        else:
            hourly.append({"hour": h["hour"], "good": h["good"] * n + (p["hourly"][i]["good"] or 0),
                           "ko": 3 * n // 2})  # fmt: skip
    return {
        "uap": {"id": "UAP2", "name": "UAP 2 · Injection"},
        "cell": {"id": cell_id, "name": "Cellule 3"},
        "date": f"{epi.DAYS[local.weekday()]} {local.day} {epi.MONTHS[local.month - 1]}",
        "currentShift": shift,
        "stations": others + [mine],
        "hourly": hourly,
    }


@app.get("/api/cells/{cell_id}/alerts")
def alerts(cell_id: str) -> list:
    """Open alerts of the cell: the workstation check, the quality KO of the scenario and
    the parts released as model errors, EPI's Safety issues and operator reports."""
    local, shift, _, _ = epi.context()
    s = snapshot()
    base = {"cellId": cell_id, "stationId": STATION, "shift": shift["code"]}
    out = [a for a in epi.alerts(cell_id) if not a["id"].startswith("requal-")]
    for i in check_issue(s, local.isoformat()):
        if i["id"] not in epi.DONE:
            out.append({
                **base, "id": i["id"], "category": "POSTE", "action": "NONE", "priority": False,
                "title": "Poste non conforme à la prise de poste",
                "detail": "Objet dans le passage · vérification de l'espace de travail",
                "when": f"depuis {_hhmm(local)}", **epi.ack(i["id"]),
            })  # fmt: skip
    for e in s["events"]:
        aid = f"qual-{s['run']}-{e['part']}"
        if aid in epi.DONE:
            continue
        waiting = s["awaiting"] and e is s["events"][-1] and not e["released"]
        if e["released"]:
            title = f"Pièce n° {e['part']} laissée passer par l’opérateur"
            detail = "Le modèle qualité l’avait classée KO : erreur modèle à confirmer"
            action = "VALIDATE"
        elif waiting:
            title = f"Pièce n° {e['part']} KO, en attente de l’opérateur"
            detail = "Production arrêtée jusqu’à la confirmation"
            action = "NONE"
        else:
            continue  # KO confirmed by the operator: part scrapped, nothing to do
        out.append({
            **base, "id": aid, "category": "QUALITE", "title": title, "detail": detail,
            "when": _hhmm(e["at"]), "priority": waiting, "action": action, **epi.ack(aid),
        })  # fmt: skip
    return out


@app.post("/api/alerts/{alert_id}/acknowledge", status_code=204)
def acknowledge(alert_id: str) -> Response:
    return epi.acknowledge(alert_id)


@app.post("/api/alerts/{alert_id}/decision", status_code=204)
def decide_alert(alert_id: str) -> Response:
    return epi.decide_alert(alert_id)


@app.post("/api/alerts/{alert_id}/maintenance", status_code=204)
def call_maintenance(alert_id: str) -> Response:
    return epi.call_maintenance(alert_id)


@app.get("/api/stations/{station_id}/detail")
def station_detail(station_id: str) -> dict:
    """EPI's station history; for C3·P06 the counters are the scenario's."""
    out = epi.station_detail(station_id)
    if station_id == STATION:
        p = production(snapshot())
        out.update(
            good=p["good"], ko=p["ko"], expectedNow=p["expectedNow"],
            delta=p["good"] - p["expectedNow"],
            efficiencyPct=round(100 * p["good"] / max(1, p["expectedNow"])),
            koRatePct=round(100 * p["ko"] / max(1, p["good"] + p["ko"]), 1),
        )  # fmt: skip
    return out


@app.post("/api/stations/{station_id}/report", status_code=204)
def report(station_id: str) -> Response:
    return epi.report(station_id)


@app.get("/api/safety-demo/stream.mjpg")
def stream():
    if not safety["on"]:
        return Response(status_code=404)
    return epi.stream()


@app.get("/api/scenario/status")
def status() -> dict:
    s = snapshot()
    s["events"] = [{**e, "at": e["at"].isoformat()} for e in s["events"]]
    s.pop("base", None)
    return s | {"safety": safety["on"], "pattern": QUALITY_PATTERN}
