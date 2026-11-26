"""Bounded synthetic twelve-station event producer for the real Core HTTP API.

It simulates results and machine cycles. It does not run a vision model.
"""

from __future__ import annotations

import argparse
import random
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from visionhub.contracts import (
    Decision,
    Event,
    FrameMeta,
    QualityDetails,
    SafetyDetails,
    Thresholds,
    UseCase,
    WorkstationDetails,
)
from visionhub.integration.edge_events import EdgeEvent, EdgeEventBatch, EdgeEventType
from visionhub.production.contracts import (
    AIPrediction,
    Correction,
    Disposition,
    ErrorCode,
    InferenceError,
    Part,
    PartVerdict,
    Shift,
)

NAMESPACE = uuid.UUID("13864212-4af5-4e5d-b85d-0f61df927da0")
THRESHOLDS = Thresholds(low=0.4, high=0.7)


def identifier(*parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(map(str, parts))))


def make_events(
    *, stations: int = 12, cycles: int = 8, seed: int = 41, now: datetime | None = None
) -> list[EdgeEventBatch]:
    """Create reproducible event content for a fixed timestamp and seed."""
    if not 1 <= stations <= 12 or not 1 <= cycles <= 100:
        raise ValueError("stations must be 1..12 and cycles 1..100")
    now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    run_key = f"{seed}:{now.isoformat()}"
    rng = random.Random(seed)
    batches = []
    for number in range(1, stations + 1):
        station = f"WS-{number:02d}"
        inactive = number == 12
        base = (
            now - timedelta(minutes=35)
            if inactive
            else now - timedelta(seconds=max(90, cycles * 10 + 60))
        )
        sequence = 0
        events = []

        def add(
            kind: EdgeEventType,
            payload: object,
            when: datetime,
            _station: str = station,
            _events: list[EdgeEvent] = events,
            **headers: object,
        ) -> None:
            nonlocal sequence
            sequence += 1
            _events.append(
                EdgeEvent(
                    event_id=identifier(run_key, _station, sequence),
                    event_type=kind,
                    station_id=_station,
                    edge_sequence=sequence,
                    occurred_at=when,
                    simulated=True,
                    payload=payload,
                    **headers,
                )
            )

        shift_id = identifier(run_key, station, "shift")
        shift = Shift(
            shift_id=shift_id,
            station_id=station,
            name="demo",
            status="OPEN",
            started_at=base - timedelta(minutes=2),
            planned_duration_min=480,
            target_parts=cycles * 8,
        )
        add(EdgeEventType.SHIFT_OPENED, {"kind": "shift", "shift": shift}, shift.started_at)
        add(
            EdgeEventType.MODEL_STATUS,
            {
                "kind": "model.status",
                "use_case": "quality",
                "model_name": "argos-demo-quality",
                "model_version": "1",
                "loaded": True,
            },
            base - timedelta(minutes=1),
            use_case=UseCase.QUALITY,
        )
        add(
            EdgeEventType.EQUIPMENT_STATUS,
            {
                "kind": "equipment.status",
                "equipment_id": f"{station}-CAM-Q",
                "equipment_type": "camera",
                "status": "down" if number == 5 else "ok",
            },
            base,
            camera_id="CAM-Q",
        )
        if inactive:
            batches.append(EdgeEventBatch(station_id=station, sent_at=now, events=events))
            continue
        for index in range(cycles):
            when = base + timedelta(seconds=10 * index)
            cycle_id = f"DEMO-{now:%Y%m%d%H%M%S}-{index + 1:03d}"
            part_id = identifier(run_key, station, cycle_id, "part")
            if number == 2 and index < max(2, cycles // 2):
                verdict = PartVerdict.NOK
            elif number == 5 and index == 0:
                verdict = PartVerdict.ERROR
            else:
                verdict = rng.choices(
                    [PartVerdict.OK, PartVerdict.NOK, PartVerdict.HOLD], weights=[8, 1, 1]
                )[0]
            decision = {
                PartVerdict.OK: Decision.CONFORME,
                PartVerdict.NOK: Decision.ANOMALIE,
                PartVerdict.HOLD: Decision.A_VERIFIER,
            }.get(verdict)
            score = {PartVerdict.OK: 0.12, PartVerdict.NOK: 0.88, PartVerdict.HOLD: 0.55}.get(
                verdict
            )
            prediction = None
            error = None
            if decision is not None:
                inference_id = identifier(run_key, station, cycle_id, "inference")
                inference = Event(
                    event_id=inference_id,
                    frame=FrameMeta(
                        frame_id=f"cycle:{station}:{cycle_id}",
                        timestamp=when,
                        workstation_id=station,
                        camera_id="CAM-Q",
                    ),
                    use_case=UseCase.QUALITY,
                    score=score,
                    latency_ms=12.0 + index,
                    model_name="argos-demo-quality",
                    model_version="1",
                    details=QualityDetails(),
                    decision=decision,
                    thresholds_used=THRESHOLDS,
                )
                add(
                    EdgeEventType.INFERENCE,
                    {"kind": "inference", "event": inference},
                    when,
                    camera_id="CAM-Q",
                    cycle_id=cycle_id,
                    use_case=UseCase.QUALITY,
                    model_name=inference.model_name,
                    model_version="1",
                    score=score,
                    decision=decision,
                )
                prediction = AIPrediction(
                    verdict=verdict,
                    ai_decision=decision,
                    score=score,
                    model_name="argos-demo-quality",
                    model_version="1",
                    thresholds_used=THRESHOLDS,
                    event_id=inference_id,
                    latency_ms=inference.latency_ms,
                )
            else:
                error = InferenceError(
                    code=ErrorCode.CAPTURE_FAILED, message="synthetic demo error"
                )
            part = Part(
                part_id=part_id,
                station_id=station,
                cycle_id=cycle_id,
                shift_id=shift_id,
                created_at=when,
                trigger_source="plc_simulated",
                camera_id="CAM-Q",
                image_sha256=None,
                predicted_verdict=verdict,
                prediction=prediction,
                error=error,
                effective_verdict=verdict,
                correction_count=0,
            )
            add(
                EdgeEventType.PART_RECORDED,
                {"kind": "part.recorded", "part": part},
                when,
                camera_id="CAM-Q",
                cycle_id=cycle_id,
                part_id=part_id,
                use_case=UseCase.QUALITY,
                verdict=verdict,
            )
            if number == 2 and index == 0:
                correction = Correction(
                    correction_id=identifier(run_key, station, part_id, "correction"),
                    part_id=part_id,
                    sequence=1,
                    previous_verdict=PartVerdict.NOK,
                    new_verdict="OK",
                    reason="Synthetic physical inspection",
                    actor_role="operator",
                    physical_inspection=True,
                    at=when + timedelta(seconds=1),
                )
                add(
                    EdgeEventType.PART_CORRECTED,
                    {"kind": "part.corrected", "correction": correction},
                    correction.at,
                    part_id=part_id,
                    verdict=PartVerdict.OK,
                )
            if number == 2 and index == 1:
                add(
                    EdgeEventType.PART_DISPOSITION,
                    {
                        "kind": "part.disposition",
                        "part_id": part_id,
                        "disposition": Disposition.QUARANTINED,
                    },
                    when + timedelta(seconds=2),
                    part_id=part_id,
                )
        if number in (3, 4):
            use_case = UseCase.SAFETY if number == 3 else UseCase.WORKSTATION
            details = SafetyDetails(person_count=0) if number == 3 else WorkstationDetails()
            for index in range(3 if number == 3 else 1):
                when = base + timedelta(seconds=20 + index * 10)
                inference = Event(
                    event_id=identifier(run_key, station, use_case, index),
                    frame=FrameMeta(
                        frame_id=f"synthetic:{station}:{index}",
                        timestamp=when,
                        workstation_id=station,
                        camera_id="CAM-H",
                    ),
                    use_case=use_case,
                    score=0.9,
                    latency_ms=15.0,
                    model_name=f"argos-demo-{use_case.value}",
                    model_version="1",
                    details=details,
                    decision=Decision.ANOMALIE,
                    thresholds_used=THRESHOLDS,
                )
                add(
                    EdgeEventType.INFERENCE,
                    {"kind": "inference", "event": inference},
                    when,
                    camera_id="CAM-H",
                    use_case=use_case,
                    score=0.9,
                    decision=Decision.ANOMALIE,
                )
        if number == 6:
            add(
                EdgeEventType.OPERATOR_REPORT,
                {
                    "kind": "operator.report",
                    "report_id": identifier(run_key, station, "report"),
                    "category": "equipment",
                    "severity": "warning",
                    "message": "Synthetic operator report",
                },
                base + timedelta(seconds=30),
            )
        batches.append(EdgeEventBatch(station_id=station, sent_at=now, events=events))
    return batches


def run(
    api_url: str,
    *,
    stations: int = 12,
    cycles: int = 8,
    seed: int = 41,
    replay: bool = True,
    out_of_order: bool = True,
    resolve: bool = True,
) -> dict:
    batches = make_events(stations=stations, cycles=cycles, seed=seed)
    accepted = duplicates = rejected = 0
    with httpx.Client(base_url=api_url, timeout=15.0) as client:
        for batch in batches:
            payloads = [batch]
            if out_of_order and batch.station_id == "WS-02" and len(batch.events) > 4:
                # A later sequence arrives first; each batch itself remains sorted.
                first, rest = batch.events[:4], batch.events[4:]
                payloads = [
                    EdgeEventBatch(station_id=batch.station_id, sent_at=batch.sent_at, events=rest),
                    EdgeEventBatch(
                        station_id=batch.station_id, sent_at=batch.sent_at, events=first
                    ),
                ]
            for piece in payloads:
                response = client.post("/ingest/v1/events", json=piece.model_dump(mode="json"))
                response.raise_for_status()
                for result in response.json()["results"]:
                    accepted += result["status"] == "accepted"
                    duplicates += result["status"] == "duplicate"
                    rejected += result["status"] == "rejected"
            if replay:
                response = client.post("/ingest/v1/events", json=batch.model_dump(mode="json"))
                response.raise_for_status()
                duplicates += sum(r["status"] == "duplicate" for r in response.json()["results"])
        if resolve:
            alerts = client.get("/api/v1/alerts", params={"station_id": "WS-03"}).json()
            safety = next((alert for alert in alerts if alert["use_case"] == "safety"), None)
            if safety:
                client.post(f"/api/v1/alerts/{safety['alert_id']}/resolve").raise_for_status()
        health = client.get("/health").json()
        kpi = client.get("/api/v1/kpi").json()
        alerts = client.get("/api/v1/alerts").json()
    return {
        "mode": "synthetic; no computer vision inference",
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
        "health": health,
        "kpi": {
            k: kpi[k] for k in ("total_parts", "ok_parts", "nok_parts", "hold_parts", "error_parts")
        },
        "alerts": len(alerts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8020")
    parser.add_argument("--stations", type=int, default=12)
    parser.add_argument("--cycles", type=int, default=8)
    parser.add_argument("--seed", type=int, default=41)
    args = parser.parse_args()
    print(run(args.api_url, stations=args.stations, cycles=args.cycles, seed=args.seed))


if __name__ == "__main__":
    main()
