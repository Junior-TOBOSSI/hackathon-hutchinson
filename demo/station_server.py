"""HOVIS demo: the server of ONE station (one per active station, like one edge PC each).

    STATION_ID="C3·P06" PROFILE=0 PORT=8001 python -m uvicorn demo.station_server:app --port 8001
    # normally started by demo/start.ps1 (one window per station), behind demo/cell_server.py

It serves its MODELS through an API and calls them itself, so that the server log shows
every model request (``POST /api/models/...``) and its verdict:

- ``POST /api/models/workstation/check``  (body: image) -> workstation analyzer
- ``POST /api/models/quality/classify``   (body: image) -> quality model qualite702 v1

and the station's screen (``/api/stations/{id}/live``, CONFIRMER, LAISSER PASSER...), plus
``/api/station/summary`` and ``/api/station/alerts`` read by the cell server.

Scenario of the station (``PROFILE`` = its rank among the active stations, 0-5):
0. IDLE until POST /api/scenario/restart (the ARGOS logo of THIS station's screen,
   through the cell server): each station is started by hand, on its own.
1. WORKSTATION CHECK, done ONCE, one photo every ``CHECK_PERIOD`` s (2.5), each photo sent
   to the workstation model: profiles 0-1 (Machine cell variant) anomaly_04 -> KO, the
   same photo -> KO, good_04 -> OK; profile 2 (Press cell, ANOTHER workstation), 3
   (Electrical bench), 4 (Machine cell), 5 (Machine cell variant, another photo): a
   conforming photo, OK at once.
2. QUALITY: one part every ``QUALITY_PERIOD`` s (3) sent to the quality model,
   validation-burst photos only. Good part or KO part: the CELL decides for all its
   stations (``CELL_URL``, at most 2 KO in any 200
   consecutive parts of the cell, the first on the part n° 4 of the first station).
   ``QUALITY_MODE`` manual (default): a NOK part WAITS for the operator, CONFIRMER or
   LAISSER PASSER (model error). auto: the operator is not asked, the NOK part is
   scrapped and the line goes on.
3. SAFETY (``SAFETY=1``): EPI's live analysis of the webcam, or of a VIDEO FILE
   (``VIDEO=path``): it plays ONCE when the operator presses « LANCER LA VIDÉO », at its
   own speed; at its end the camera closes. Faces hidden as with the webcam.

Counters: the shift so far (EPI's simulation) frozen when the activity starts, plus the
demo parts; the plan advances at the demo pace only while the line produces.
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
import httpx
import numpy as np
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "usecases/safety/notebooks")]

import hovis_demo as epi  # noqa: E402  EPI's demo: shift, simulated production, webcam loop

from usecases.quality.model702 import Quality702Analyzer  # noqa: E402
from usecases.workstation.evaluate import build_analyzer, shared_detector  # noqa: E402
from usecases.workstation.render import describe, render  # noqa: E402
from usecases.workstation.station import load_station, normal_photos  # noqa: E402
from visionhub.config import load_use_case_config  # noqa: E402
from visionhub.contracts import FrameMeta, UseCase  # noqa: E402
from visionhub.decision import decide  # noqa: E402

STATION = os.environ.get("STATION_ID", "C3·P06")
PROFILE = int(os.environ.get("PROFILE", "0"))
PORT = int(os.environ.get("PORT", "8001"))
SELF = f"http://127.0.0.1:{PORT}"
CHECK_KO = ["anomaly/anomaly_04.png", "anomaly/anomaly_04.png", "good/good_04.png"]
PROFILES = [  # (section, workstation check photos, title)
    ("machine_cell_variant", CHECK_KO, "Machine cell variant"),
    ("machine_cell_variant", CHECK_KO, "Machine cell variant"),
    ("press_cell", ["good/good_01.png"], "Press cell"),
    ("electrical_bench", ["good/good_01.png"], "Electrical bench"),
    ("machine_cell", ["good/good_01.png"], "Machine cell (top view)"),
    ("machine_cell_variant", ["good/good_03.png"], "Machine cell variant"),
]
SECTION, CHECK_PHOTOS, TITLE = PROFILES[PROFILE % len(PROFILES)]
# WORKSTATION chooses the workstation this station checks, instead of its profile's:
# "press_cell" (conforming photo: OK at once) or "press_cell:nok" (object in the
# passage: NOK, NOK, then OK). anomaly_04 gives NOK and good_04 OK on all 5 workstations.
SECTIONS = ("machine_cell_variant", "press_cell", "electrical_bench", "machine_cell", "cnc_cell")
if os.environ.get("WORKSTATION"):
    SECTION, _, START = os.environ["WORKSTATION"].strip().lower().partition(":")
    if SECTION not in SECTIONS or START not in ("", "ok", "nok"):
        raise SystemExit(
            f"WORKSTATION={os.environ['WORKSTATION']!r}: one of {SECTIONS}, optionally :ok / :nok"
        )
    CHECK_PHOTOS = CHECK_KO if START == "nok" else ["good/good_04.png"]
    TITLE = ""  # read from the workstation file at load time
DATA = REPO / "data"
CHECK_PERIOD = float(os.environ.get("CHECK_PERIOD", "2.5"))
QUALITY_PERIOD = float(os.environ.get("QUALITY_PERIOD", "3"))
VALIDATED_HOLD = float(os.environ.get("VALIDATED_HOLD", "3"))
VIDEO = os.environ.get("VIDEO", "")  # a video file instead of the webcam (Safety)
# Playback speed of that video: 1 = real time, 0.5 = twice slower, 2 = twice faster
VIDEO_SPEED = min(4.0, max(0.1, float(os.environ.get("VIDEO_SPEED", "1") or 1)))
CELL_URL = os.environ.get("CELL_URL", "http://127.0.0.1:8000")  # decides the KO parts
# manual: a NOK part stops the line until the operator answers; auto: it does not.
QUALITY_MODE = "auto" if os.environ.get("QUALITY_MODE", "manual").lower() == "auto" else "manual"
VAL_BURSTS = {"R08", "R12", "R14", "R21", "R26", "R27"}  # qualite702 v1 report

log = logging.getLogger(f"poste {STATION}")
lock = threading.Lock()
state: dict = {"run": 0}
models: dict = {}  # loaded at startup: workstation analyzer, quality analyzer
images: dict[int, bytes] = {}  # annotated workstation photos returned by the check model


def _jpeg(image: np.ndarray, width: int = 640) -> bytes:
    h, w = image.shape[:2]
    small = cv2.resize(image, (width, int(width * h / w)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _display_part(image: np.ndarray) -> np.ndarray:
    """For the SCREEN only: the quality photos are tiny (126 x 86) and very dark. Local
    contrast (CLAHE), a gamma of 0.5 and enlargement make the groove visible. The model
    always analyses the ORIGINAL photo."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(lab[..., 0])
    bright = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    gamma = (255 * (np.arange(256) / 255) ** 0.5).astype(np.uint8)
    return cv2.resize(cv2.LUT(bright, gamma), None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)


def _hhmm(t: datetime) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _decode(body: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("body is not an image")
    return image


# ------------------------------------------------------------------ models (served by API)


def load_models() -> None:
    global TITLE
    station = load_station(SECTION, DATA)
    TITLE = TITLE or station.get("title", SECTION)
    judged = {str(station["dataset_dir"] / f) for f in CHECK_PHOTOS}
    normal = [p for p in normal_photos(station) if p not in judged]  # judged, never learned
    analyzer, thresholds = build_analyzer(station, normal, {}, detector=shared_detector({}))
    models["workstation"] = (analyzer, thresholds, station)
    config = load_use_case_config(UseCase.QUALITY)
    quality = Quality702Analyzer()
    quality.load({**config.params, "device": "cpu"})
    models["quality"] = (quality, config.thresholds)


def check_model(image: np.ndarray, name: str) -> dict:
    analyzer, thresholds, _ = models["workstation"]
    start = time.perf_counter()
    result = analyzer.analyze(
        image, FrameMeta(frame_id=name, workstation_id=STATION, camera_id="front")
    )
    decision = decide(result.score, thresholds)
    image_id = len(images) + 1
    images[image_id] = _jpeg(render(image, analyzer, result, decision))
    return {
        "model": f"{analyzer.name} {analyzer.version} · {SECTION}",
        "verdict": "OK" if decision.value == "conforme" else "KO",
        "score": round(result.score, 3),
        "findings": describe(result),
        "imageId": image_id,
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


def classify_model(image: np.ndarray, name: str) -> dict:
    quality, thresholds = models["quality"]
    start = time.perf_counter()
    result = quality.analyze(
        image, FrameMeta(frame_id=name, workstation_id=STATION, camera_id="part")
    )
    ko = decide(result.score, thresholds).value != "conforme"
    return {
        "model": f"{quality.name} {quality.version}",
        "verdict": "KO" if ko else "OK",
        "score_nok": round(result.score, 4),
        "defect": quality.last["defect"],
        "probabilities": quality.last["probabilities"],
        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
    }


# ------------------------------------------------------------------ scenario


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


def next_is_ko(cell: httpx.Client, index: int) -> bool:
    """Good part or KO part? The CELL decides, for all its stations together: at most 2 KO
    in any 200 consecutive parts of the cell, the first one on the part n° 4 of the first
    station there. Without a cell server (station run alone): the same rule, alone."""
    try:
        params = {"station": STATION, "index": index}
        return bool(cell.post("/api/cell/next-part", params=params).json()["ko"])
    except httpx.HTTPError:
        return index % 100 == 3


def pick_photo(ko: bool, ok: list[Path], nok: list[Path]) -> Path:
    """Next photo of the right kind; each station starts at another place in the lists.
    The model classifies every validation photo right (0 error on 103 OK / 67 NOK), so a
    good photo gives an OK verdict and a NOK photo a KO verdict."""
    key, photos = ("n_nok", nok) if ko else ("n_ok", ok)
    with lock:
        i = state[key]
        state[key] += 1
    return photos[(i + 11 * PROFILE) % len(photos)]


def reset() -> None:
    with lock:
        run = state.get("run", 0) + 1
        state.clear()
        state.update(
            run=run,
            phase="IDLE",
            step=0,
            phase_since=time.monotonic(),
            checks={},
            validated_at=None,
            part=None,
            part_jpeg=None,
            good=0,
            ko=0,
            awaiting=False,
            model_errors=0,
            active_s=0.0,
            base=None,
            events=[],
            n_ok=0,
            n_nok=0,
        )


def base_production() -> dict:
    """The shift so far for this station (EPI's simulation; P06 = the cell's base)."""
    _, _, _, prod = epi.context()
    if STATION == epi.STATION:
        return prod
    st = epi.station_summary(STATION, prod, [])
    return {
        "good": st["good"],
        "ko": st["ko"],
        "expectedNow": st["expectedNow"],
        "shiftTarget": st["target"],
        "hourly": prod["hourly"],
    }


def loop() -> None:
    """The station's scenario. Every photo goes through the model API (see the log)."""
    client = httpx.Client(base_url=SELF, timeout=30)
    cell = httpx.Client(base_url=CELL_URL, timeout=5)
    ok_photos, nok_photos = quality_photos()
    workstation = models["workstation"][2]["dataset_dir"]
    last = time.monotonic()
    while True:
        time.sleep(0.1)
        now = time.monotonic()
        tick, last = now - last, now
        with lock:
            phase, since, step, run = (
                state["phase"],
                state["phase_since"],
                state["step"],
                state["run"],
            )
            need_check = phase == "CHECK" and step not in state["checks"]
        if phase == "IDLE":
            continue
        if need_check:  # the photo shown now is sent to the workstation model
            name = CHECK_PHOTOS[step]
            body = (workstation / name).read_bytes()
            res = client.post(f"/api/models/workstation/check?name={name}", content=body).json()
            with lock:
                if state["run"] == run:
                    state["checks"][step] = res
                    state["phase_since"] = time.monotonic()  # shown CHECK_PERIOD from now
            continue
        with lock:
            if state["run"] != run:
                continue
            if phase == "CHECK" and now - since >= CHECK_PERIOD:
                if state["checks"][step]["verdict"] == "OK":
                    stamp = datetime.now().astimezone().isoformat()
                    state.update(phase="VALIDATED", phase_since=now, validated_at=stamp)
                    log.info("workstation validated: the activity can start")
                else:
                    state.update(step=(step + 1) % len(CHECK_PHOTOS))
                continue
            if phase == "VALIDATED" and now - since >= VALIDATED_HOLD:
                state.update(
                    phase="RUNNING", phase_since=now - QUALITY_PERIOD, base=base_production()
                )
                continue
            if phase != "RUNNING":
                continue
            if not state["awaiting"]:
                state["active_s"] += tick  # the plan advances only while producing
            if state["awaiting"] or now - since < QUALITY_PERIOD:
                continue
            index = state["good"] + state["ko"]
        path = pick_photo(next_is_ko(cell, index), ok_photos, nok_photos)
        res = client.post(
            f"/api/models/quality/classify?name={path.name}", content=path.read_bytes()
        ).json()
        ko = res["verdict"] == "KO"
        at = datetime.now().astimezone()
        image = cv2.imread(str(path))
        with lock:
            if state["run"] != run:
                continue
            number = state["good"] + state["ko"] + 1
            state["good" if not ko else "ko"] += 1
            if ko:
                wait = QUALITY_MODE == "manual"
                state["events"].append({"part": number, "at": at, "released": False})
                log.info(
                    "part %d NOK (%s): %s",
                    number,
                    res["defect"],
                    "waiting for the operator" if wait else "scrapped, the line goes on (auto)",
                )
            state.update(
                phase_since=time.monotonic(),
                awaiting=ko and QUALITY_MODE == "manual",
                part_jpeg=_jpeg(_display_part(image), 480),
                part={
                    "number": number,
                    "verdict": res["verdict"],
                    "score": res["score_nok"],
                    "jointsDetected": {"NOK_SANS": 0, "NOK_DOUBLE": 2}.get(res["defect"], 1),
                    "takenAt": at.isoformat(),
                },
            )


def snapshot() -> dict:
    with lock:
        return {k: (dict(v) if k == "checks" else v) for k, v in state.items() if k != "part_jpeg"}


def production(s: dict) -> dict:
    local, shift, _, _ = epi.context()
    base = s["base"] or base_production()
    hourly = [dict(h) for h in base["hourly"]]
    for h in hourly:
        if h["hour"] == local.hour:
            h["good"] = (h["good"] or 0) + s["good"]
    return {
        "shift": shift,
        "good": base["good"] + s["good"],
        "ko": base["ko"] + s["ko"],
        "expectedNow": base["expectedNow"] + int(s["active_s"] / QUALITY_PERIOD),
        "shiftTarget": base["shiftTarget"],
        "hourly": hourly,
    }


def current_check(s: dict) -> dict | None:
    return s["checks"].get(s["step"])


def issues_of(s: dict, now: str) -> tuple[list[dict], bool]:
    camera = False
    issues: list[dict] = []
    if safety["on"]:
        with epi.lock:
            issues, camera = list(epi.state["issues"]), bool(epi.state["n"])
    check = current_check(s)
    if s["phase"] == "CHECK" and check and check["verdict"] == "KO":
        issues.append(
            {
                "id": f"poste-check-{s['run']}-{STATION}",
                "category": "POSTE",
                "label": "Poste non conforme",
                "instruction": "Dégagez le passage",
                "since": now,
            }
        )
    return issues, camera


# ------------------------------------------------------------------ app

app = FastAPI(title=f"HOVIS station {STATION}")
safety: dict = {"on": False}


@app.on_event("startup")
def _start() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s | %(message)s")
    os.chdir(REPO)
    load_models()
    reset()
    threading.Thread(target=loop, daemon=True).start()
    log.info("ready: workstation %s, check %s, NOK mode %s", TITLE, CHECK_PHOTOS, QUALITY_MODE)
    weights = REPO / epi.WEIGHTS
    video = VIDEO
    if (video or os.environ.get("SAFETY", "0") == "1") and weights.exists():
        if video:  # a video file instead of the webcam: EPI's loop opens it as its camera
            epi.CAMERA, epi.reader, epi.newest_frame = video, video_reader, video_newest_frame
        threading.Thread(target=epi.loop, daemon=True).start()
        safety["on"] = True
        source = f"video {Path(video).name}" if video else f"webcam {epi.CAMERA}"
        log.info("safety: EPI live analysis of the %s (%s)", source, weights.name)


video_play = threading.Event()  # « LANCER LA VIDÉO » on the operator screen
video_state = {"playing": False}
video_frame: dict = {"img": None}  # the video image EPI's loop analyses next


def video_newest_frame(cap):  # noqa: ARG001  replaces EPI's newest_frame for a video
    """EPI's loop decodes the camera image only when it analyses one; for a video the
    reader below already decoded it: hand it over."""
    return video_frame["img"]


def video_reader(cap) -> None:
    """Replaces EPI's camera reader for a VIDEO FILE. The video waits for the operator's
    « LANCER LA VIDÉO » button, then plays ONCE at its own speed (a file would otherwise be
    read as fast as possible). At the end the camera goes quiet and its issues are cleared:
    with no infraction left, the camera image closes on the operator screen."""
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    period = 1.0 / ((fps if 1 <= fps <= 120 else 25.0) * VIDEO_SPEED)
    if not cap.isOpened():
        log.error("safety: cannot open the video %s", epi.CAMERA)
        return
    while True:
        video_play.wait()
        video_play.clear()
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        video_state["playing"] = True
        log.info("safety: video started (speed x%s)", VIDEO_SPEED)
        next_at = time.monotonic()
        while not video_play.is_set():  # pressed again: restart from the beginning
            ok, frame = cap.read()
            if not ok:
                break
            video_frame["img"] = frame
            epi.latest["frame"] = True  # EPI's flag: a fresh image is waiting
            next_at += period
            time.sleep(max(0.0, next_at - time.monotonic()))
        if video_play.is_set():
            continue
        epi.latest["frame"], video_frame["img"] = None, None  # end of the video: nothing to analyse
        time.sleep(1.0)  # let the analysis of the last frame finish
        with epi.lock:
            epi.state["issues"] = []
        video_state["playing"] = False
        log.info("safety: video finished, camera closed")


@app.post("/api/models/workstation/check")
async def api_check(request: Request, name: str = "photo") -> dict:
    """Workstation model: is the station like its reference? (body: the photo)"""
    image = _decode(await request.body())
    res = await run_in_threadpool(check_model, image, name)
    log.info(
        "workstation model <- %s : %s %s (%s ms)",
        name,
        res["verdict"],
        res["findings"],
        res["latency_ms"],
    )
    return res


@app.post("/api/models/quality/classify")
async def api_classify(request: Request, name: str = "photo") -> dict:
    """Quality model: classification of the part photo (body: the photo)."""
    image = _decode(await request.body())
    res = await run_in_threadpool(classify_model, image, name)
    log.info(
        "quality model <- %s : %s score_nok=%s (%s ms)",
        name,
        res["verdict"],
        res["score_nok"],
        res["latency_ms"],
    )
    return res


@app.get("/api/stations/{station_id}/live")
def live(station_id: str) -> dict:
    s = snapshot()
    local = datetime.now().astimezone()
    now = local.isoformat()
    issues, camera = issues_of(s, now)
    p = production(s)
    check = current_check(s) or {"verdict": "OK", "findings": [], "imageId": 0}
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
            "steps": len(CHECK_PHOTOS),
            "verdict": check["verdict"],
            "findings": check["findings"],
            "imageUrl": f"/api/scenario/workstation.jpg?station={STATION}&id={check['imageId']}",
            "validatedAt": s["validated_at"],
            "section": TITLE,
        },
        "part": {
            **{k: part[k] for k in ("number", "verdict", "jointsDetected", "score", "takenAt")},
            "imageUrl": f"/api/scenario/part.jpg?station={STATION}&n={part['number']}"
            if s["part"]
            else "/img/demo-piece-ok.svg",
            "awaitingConfirmation": s["awaiting"],
        },
        "counters": {"good": p["good"], "ko": p["ko"]},
        "objective": {
            "shiftTarget": p["shiftTarget"],
            "expectedNow": p["expectedNow"],
            "perHour": epi.PER_HOUR,
        },
        "hourly": p["hourly"],
        "issues": issues,
        "frontSnapshotUrl": f"/api/safety-demo/stream.mjpg?station={STATION}" if camera else None,
        "checks": {
            "securite": not any(i["category"] != "POSTE" for i in issues),
            "poste": not any(i["category"] == "POSTE" for i in issues),
            "qualite": not s["awaiting"],
            "koRatePct": round(100 * p["ko"] / max(1, p["good"] + p["ko"]), 1),
        },
        "qualityModelVersion": "qualite702 v1",
        "partCameraOnline": True,
        # Video instead of the webcam: the operator screen shows « LANCER LA VIDÉO »
        "video": {"available": bool(VIDEO), "playing": video_state["playing"]} if VIDEO else None,
    }


@app.get("/api/scenario/workstation.jpg")
def workstation_jpg(id: int = 0, station: str = "") -> Response:
    return Response(
        images.get(id, b""), media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@app.get("/api/scenario/part.jpg")
def part_jpg(n: int = 0, station: str = "") -> Response:
    with lock:
        jpeg = state.get("part_jpeg") or b""
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/stations/{station_id}/parts/confirm", status_code=204)
def confirm(station_id: str) -> Response:
    with lock:
        state.update(awaiting=False, phase_since=time.monotonic() - QUALITY_PERIOD)
    log.info("operator: CONFIRMER (KO kept)")
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/release", status_code=204)
def release(station_id: str) -> Response:
    with lock:
        if state["awaiting"]:
            state["ko"] -= 1
            state["good"] += 1
            state["model_errors"] += 1
            if state["part"]:
                state["part"]["verdict"] = "OK"
            if state["events"]:
                state["events"][-1]["released"] = True
        state.update(awaiting=False, phase_since=time.monotonic() - QUALITY_PERIOD)
    log.info("operator: LAISSER PASSER (model error counted)")
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/{number}/requalify", status_code=204)
def requalify(station_id: str, number: int) -> Response:
    return release(station_id)


@app.post("/api/stations/{station_id}/video/play", status_code=204)
def play_video(station_id: str) -> Response:
    """« LANCER LA VIDÉO »: the station's video plays once (from the start)."""
    if VIDEO:
        video_play.set()
    return Response(status_code=204)


@app.post("/api/scenario/restart", status_code=204)
def restart() -> Response:
    reset()
    with lock:
        state.update(phase="CHECK", phase_since=time.monotonic())
    log.info("simulation started: workstation check")
    return Response(status_code=204)


@app.get("/api/station/summary")
def station_summary() -> dict:
    """This station as a team leader card, plus the counters of its detail page."""
    s = snapshot()
    issues, _ = issues_of(s, datetime.now().astimezone().isoformat())
    p = production(s)
    cats = {i["category"] for i in issues}
    status = (
        "SECURITE"
        if cats & {"SECURITE_EPI", "COMPORTEMENT"}
        else "OBJET"
        if "POSTE" in cats
        else "QUALITE"
        if s["awaiting"]
        else "OK"
    )
    return {
        "id": STATION,
        "product": "raccord QC 702",
        "good": p["good"],
        "target": p["shiftTarget"],
        "expectedNow": p["expectedNow"],
        "ko": p["ko"],
        "status": status,
        "hourly": p["hourly"],
    }


@app.get("/api/station/alerts")
def station_alerts() -> list:
    """Alerts of this station: workstation check, KO waiting, parts released, Safety."""
    local, shift, _, _ = epi.context()
    s = snapshot()
    issues, _ = issues_of(s, local.isoformat())
    base = {"stationId": STATION, "shift": shift["code"]}
    out = []
    for i in issues:
        poste = i["category"] == "POSTE"
        out.append(
            {
                **base,
                "id": i["id"] if STATION in i["id"] else f"{STATION}:{i['id']}",
                "category": "POSTE" if poste else "SECURITE_EPI",
                "action": "NONE",
                "priority": not poste,
                "title": "Poste non conforme à la prise de poste"
                if i["id"].startswith("poste-check")
                else i["label"],
                "detail": "Objet dans le passage · vérification de l'espace de travail"
                if poste
                else f"{i['instruction']} · vu par la caméra frontale (visage flouté)",
                "when": f"depuis {_hhmm(local)}",
            }
        )
    for e in s["events"]:
        waiting = s["awaiting"] and e is s["events"][-1] and not e["released"]
        if e["released"]:
            title = f"Pièce n° {e['part']} laissée passer par l’opérateur"
            detail, action = (
                "Le modèle qualité l’avait classée KO : erreur modèle à confirmer",
                "VALIDATE",
            )
        elif waiting:
            title = f"Pièce n° {e['part']} NOK, en attente de l’opérateur"
            detail, action = "Production arrêtée jusqu’à la confirmation", "NONE"
        else:
            continue  # KO confirmed by the operator: part scrapped, nothing to do
        out.append(
            {
                **base,
                "id": f"qual-{s['run']}-{STATION}-{e['part']}",
                "category": "QUALITE",
                "title": title,
                "detail": detail,
                "when": _hhmm(e["at"]),
                "priority": waiting,
                "action": action,
            }
        )
    return out


@app.get("/api/safety-demo/stream.mjpg")
def stream():
    if not safety["on"]:
        return Response(status_code=404)
    return epi.stream()
