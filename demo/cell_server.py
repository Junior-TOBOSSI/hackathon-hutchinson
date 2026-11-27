"""HOVIS demo: the server of cell C3 (port 8000), in front of one server per station.

    ACTIVE_STATIONS=3 python -m uvicorn demo.cell_server:app --port 8000
    # normally started by demo/start.ps1 -Stations 3

The argos-ui screens only talk to this server (the Vite proxy sends /api to port 8000).
It loads NO model: it forwards each station's requests to that station's own server
(demo/station_server.py, port 8001 + rank) and builds the team leader's cell view from
them. Cell C3 has 6 stations; the ``ACTIVE_STATIONS`` first ones of ``ORDER`` have a
server, the others show "no activity" (status ARRET).

Kept here, as in EPI's demo (usecases/safety/notebooks/hovis_demo.py, reused): login,
alerts taken in charge / closed (epi.ACK, epi.DONE), operator reports, station history.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "usecases/safety/notebooks")]

import hovis_demo as epi  # noqa: E402  EPI's demo: shift, alerts, team leader helpers

log = logging.getLogger("cellule C3")
CELL = [f"C3·P{i:02d}" for i in range(1, 7)]  # the team leader's 6 stations
ORDER = ["C3·P06", "C3·P01", "C3·P02", "C3·P03", "C3·P04", "C3·P05"]  # activation order
N_ACTIVE = max(1, min(len(ORDER), int(os.environ.get("ACTIVE_STATIONS", "1"))))
FIRST_PORT = int(os.environ.get("FIRST_STATION_PORT", "8001"))
PORTS = {sid: FIRST_PORT + k for k, sid in enumerate(ORDER[:N_ACTIVE])}  # active stations
CAMERA_STATION = ORDER[0]  # the station EPI's webcam watches (if its server has SAFETY=1)

KO_MAX = int(os.environ.get("KO_MAX", "2"))  # at most KO_MAX KO...
KO_WINDOW = int(os.environ.get("KO_WINDOW", "200"))  # ...in any KO_WINDOW consecutive parts
FIRST_KO_AT = int(os.environ.get("FIRST_KO_AT", "4"))  # a station's part n° 4: the first KO
# parts of the cell so far (all stations), cell numbers of the KO parts, first KO still due
parts: dict = {"count": 0, "ko": [], "first_due": True}
parts_lock = threading.Lock()  # sync routes run in parallel threads: one part number each

app = FastAPI(title="HOVIS cell C3")
client = httpx.AsyncClient(timeout=10)


def url(sid: str, path: str) -> str:
    return f"http://127.0.0.1:{PORTS[sid]}{path}"


async def get(sid: str, path: str):
    """JSON of a station server, or None if it is not reachable (still loading)."""
    try:
        r = await client.get(url(sid, path))
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def no_activity(sid: str, phase: str = "OFF") -> dict:
    """Operator screen of a station with no activity (or whose server is still loading:
    phase IDLE, "En attente de la prise de poste")."""
    local, shift, _, prod = epi.context()
    now = local.isoformat()
    return {
        "stationId": sid,
        "product": "raccord 702 · démo",
        "shift": shift,
        "now": now,
        "startup": {
            "phase": phase,
            "step": 0,
            "steps": 0,
            "verdict": "OK",
            "findings": [],
            "imageUrl": "",
            "validatedAt": None,
            "section": "",
        },
        "part": {
            "number": 0,
            "verdict": "OK",
            "jointsDetected": 1,
            "score": 0.0,
            "takenAt": now,
            "imageUrl": "/img/demo-piece-ok.svg",
            "awaitingConfirmation": False,
        },
        "counters": {"good": 0, "ko": 0},
        "objective": {
            "shiftTarget": prod["shiftTarget"],
            "expectedNow": 0,
            "perHour": epi.PER_HOUR,
        },
        "hourly": [{"hour": h["hour"], "good": None} for h in prod["hourly"]],
        "issues": [],
        "frontSnapshotUrl": None,
        "checks": {"securite": True, "poste": True, "qualite": True, "koRatePct": 0.0},
        "qualityModelVersion": "qualite702 v1",
        "partCameraOnline": False,
    }


def stopped(sid: str) -> dict:
    _, _, _, prod = epi.context()
    return {
        "id": sid,
        "product": "raccord QC 702",
        "good": 0,
        "target": prod["shiftTarget"],
        "expectedNow": 0,
        "ko": 0,
        "status": "ARRET",
        "hourly": None,
    }


@app.on_event("startup")
def _start() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s | %(message)s")
    for sid in CELL:
        log.info(
            "%s : %s",
            sid,
            f"serveur du poste sur le port {PORTS[sid]}" if sid in PORTS else "pas d'activité",
        )


@app.post("/api/auth/login")
def login(body: dict) -> dict:
    """Demo accounts: a team leader login (c.diaz…, or containing leader / manager / chef)
    opens the team leader view of cell C3; anything else is the operator of the 1st
    active station."""
    who = str(body.get("login", "")).lower()
    if who.startswith("c.diaz") or any(k in who for k in ("leader", "manager", "chef")):
        return {"id": "demo-tl", "name": "Team leader démo", "role": "TEAM_LEADER", "cellId": "C3"}
    return {
        "id": "demo",
        "name": "Opérateur démo",
        "role": "OPERATEUR",
        "stationId": ORDER[0],
        "cellId": "C3",
    }


# ------------------------------------------------------------------ station screens (forwarded)


@app.get("/api/stations/{station_id}/live")
async def live(station_id: str) -> dict:
    if station_id not in PORTS:
        return no_activity(station_id)
    return await get(station_id, f"/api/stations/{quote(station_id)}/live") or no_activity(
        station_id, "IDLE"
    )


async def forward_image(station: str, path: str, request: Request) -> Response:
    if station not in PORTS:
        return Response(status_code=404)
    try:
        r = await client.get(url(station, path), params=dict(request.query_params))
    except httpx.HTTPError:
        return Response(status_code=503)
    return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/scenario/workstation.jpg")
async def workstation_jpg(request: Request, station: str = ORDER[0]) -> Response:
    return await forward_image(station, "/api/scenario/workstation.jpg", request)


@app.get("/api/scenario/part.jpg")
async def part_jpg(request: Request, station: str = ORDER[0]) -> Response:
    return await forward_image(station, "/api/scenario/part.jpg", request)


async def forward_post(station_id: str, path: str) -> Response:
    if station_id in PORTS:
        try:
            await client.post(url(station_id, path))
        except httpx.HTTPError:
            return Response(status_code=503)
    return Response(status_code=204)


@app.post("/api/stations/{station_id}/parts/confirm", status_code=204)
async def confirm(station_id: str) -> Response:
    return await forward_post(station_id, f"/api/stations/{quote(station_id)}/parts/confirm")


@app.post("/api/stations/{station_id}/parts/release", status_code=204)
async def release(station_id: str) -> Response:
    return await forward_post(station_id, f"/api/stations/{quote(station_id)}/parts/release")


@app.post("/api/stations/{station_id}/parts/{number}/requalify", status_code=204)
async def requalify(station_id: str, number: int) -> Response:
    return await forward_post(
        station_id, f"/api/stations/{quote(station_id)}/parts/{number}/requalify"
    )


@app.post("/api/scenario/restart", status_code=204)
async def restart(station: str = "") -> Response:
    """The HOVIS logo of a station's screen: THAT station starts (again) its workstation
    check; the others wait for their own logo. Without ``station``: every active station
    (and the cell's alerts and part count start afresh)."""
    targets = [station] if station else list(PORTS)
    for sid in targets:
        if sid not in PORTS:
            continue  # no activity: nothing to start
        try:
            await client.post(url(sid, "/api/scenario/restart"))
            log.info("%s : simulation lancée", sid)
        except httpx.HTTPError:
            log.warning("%s : serveur du poste injoignable (encore en chargement ?)", sid)
    if not station:
        epi.ACK.clear()
        epi.DONE.clear()
        with parts_lock:
            parts.update(count=0, ko=[])
    with parts_lock:
        parts["first_due"] = True  # the next station to reach its part n° 4 gets the first KO
    return Response(status_code=204)


@app.post("/api/cell/next-part")
def next_part(station: str = "", index: int = 0) -> dict:
    """Each station asks before each part (``index`` = its part number - 1): a good part or
    a KO one? The cell numbers the parts of ALL its stations and keeps the rule:
    - at most KO_MAX (2) KO in any KO_WINDOW (200) consecutive parts of the cell;
    - the first KO comes early, on the part n° FIRST_KO_AT (4) of the first station that
      gets there (after its 3 first parts), so that the demo shows one;
    - then one KO every KO_WINDOW / KO_MAX (100) parts of the cell."""
    with parts_lock:
        return _next_part(station, index)


def _next_part(station: str, index: int) -> dict:
    n = parts["count"]
    parts["count"] += 1
    recent = [k for k in parts["ko"] if k > n - KO_WINDOW]  # KO among the last parts
    spacing = KO_WINDOW // KO_MAX
    due = (parts["first_due"] and index == FIRST_KO_AT - 1) or (
        bool(parts["ko"]) and n - parts["ko"][-1] >= spacing
    )
    ko = due and len(recent) < KO_MAX
    if ko:
        parts["ko"].append(n)
        parts["first_due"] = False
        log.info(
            "pièce n° %d de la cellule : KO, pour %s (sa pièce n° %d)", n + 1, station, index + 1
        )
    return {"index": n, "ko": ko}


@app.get("/api/safety-demo/stream.mjpg")
async def stream() -> Response:
    """EPI's webcam stream (faces hidden), from the station server that analyses it."""
    if CAMERA_STATION not in PORTS:
        return Response(status_code=404)
    req = client.build_request("GET", url(CAMERA_STATION, "/api/safety-demo/stream.mjpg"))
    try:
        r = await httpx.AsyncClient(timeout=None).send(req, stream=True)
    except httpx.HTTPError:
        return Response(status_code=503)
    if r.status_code != 200:
        await r.aclose()
        return Response(status_code=r.status_code)
    return StreamingResponse(
        r.aiter_raw(), media_type=r.headers.get("content-type"), background=None
    )


# ------------------------------------------------------------------ team leader (cell C3)


async def summaries() -> list[dict]:
    out = []
    for sid in CELL:
        s = await get(sid, "/api/station/summary") if sid in PORTS else None
        out.append(s or stopped(sid))
    return out


@app.get("/api/cells/{cell_id}/overview")
async def cell_overview(cell_id: str) -> dict:
    """The 6 stations of the cell: the active ones from their servers, the others ARRET."""
    local, shift, _, prod = epi.context()
    stations = await summaries()
    hourly = []
    for i, h in enumerate(prod["hourly"]):
        goods = [
            s["hourly"][i]["good"]
            for s in stations
            if s["hourly"] and s["hourly"][i]["good"] is not None
        ]
        hourly.append(
            {"hour": h["hour"], "good": sum(goods) if goods else None, "ko": 2 * len(goods)}
        )
    return {
        "uap": {"id": "UAP2", "name": "UAP 2 · Injection"},
        "cell": {"id": cell_id, "name": "Cellule 3"},
        "date": f"{epi.DAYS[local.weekday()]} {local.day} {epi.MONTHS[local.month - 1]}",
        "currentShift": shift,
        "hourly": hourly,
        "stations": [{k: v for k, v in s.items() if k != "hourly"} for s in stations],
    }


@app.get("/api/cells/{cell_id}/alerts")
async def alerts(cell_id: str) -> list:
    """Open alerts: those of each station server, plus the operators' reports (EPI)."""
    out = [a for a in epi.alerts(cell_id) if a["category"] == "EQUIPEMENT"]  # reports
    for sid in PORTS:
        for a in await get(sid, "/api/station/alerts") or []:
            if a["id"] not in epi.DONE:
                out.append({**a, "cellId": cell_id, **epi.ack(a["id"])})
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


@app.post("/api/stations/{station_id}/report", status_code=204)
def report(station_id: str) -> Response:
    return epi.report(station_id)


@app.get("/api/stations/{station_id}/detail")
async def station_detail(station_id: str) -> dict:
    """EPI's station history, with the counters of the station server (zero if stopped)."""
    out = epi.station_detail(station_id)
    s = await get(station_id, "/api/station/summary") if station_id in PORTS else None
    good, ko, plan = (s["good"], s["ko"], s["expectedNow"]) if s else (0, 0, 0)
    out.update(
        good=good,
        ko=ko,
        expectedNow=plan,
        delta=good - plan,
        efficiencyPct=round(100 * good / max(1, plan)) if s else 0,
        koRatePct=round(100 * ko / max(1, good + ko), 1),
        koByDefect={"absent": ko // 2, "double": ko - ko // 2},
    )
    if station_id != CAMERA_STATION:
        out["events"], out["epiCounts"] = [], [{**c, "count": 0} for c in out.get("epiCounts", [])]
    return out


@app.get("/api/scenario/status")
async def status() -> dict:
    return {"active": {sid: PORTS[sid] for sid in PORTS}, "stations": await summaries()}
