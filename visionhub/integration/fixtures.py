"""Deterministic, SYNTHETIC fixtures for the frontend mock mode and the contract docs.

Every fixture is built from the Pydantic contracts and validated before export, so the
mocks can never drift from the backend. No confidential data: everything is invented.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from visionhub import __version__
from visionhub.contracts import (
    AnomalyZone,
    BBox,
    Decision,
    DetectedObject,
    Event,
    FrameMeta,
    OperatorFeedback,
    PersonPPE,
    PPEState,
    QualityDetails,
    SafetyDetails,
    Stats,
    Thresholds,
    UseCase,
    UseCaseInfo,
    UseCaseStats,
    WorkstationDetails,
)
from visionhub.integration.core_api import Alert, OperatorReport, StationSummary
from visionhub.integration.edge_events import (
    EdgeEvent,
    EdgeEventBatch,
    EquipmentStatusPayload,
    InferencePayload,
    IngestAck,
    IngestResult,
    ModelStatusPayload,
    OperatorReportPayload,
    PartCorrectedPayload,
    PartRecordedPayload,
    ShiftPayload,
)
from visionhub.integration.mlops import (
    ArtifactRef,
    DatasetRef,
    DriftMeasure,
    EvaluationMetrics,
    ModelDeployment,
    ModelPackage,
    ModelRef,
    MonitoringMetrics,
    PreprocessingSpec,
    RetrainingPolicy,
    StationDeploymentStatus,
    TrainingConfig,
    TrainingJob,
)
from visionhub.production.contracts import (
    AIPrediction,
    Correction,
    ErrorCode,
    InferenceError,
    Part,
    PartVerdict,
    ProductionKPI,
    Shift,
    ShiftReport,
)
from visionhub.production.kpi import Tally, compute_kpi

T0 = datetime(2026, 11, 26, 6, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=3)
NS = uuid.UUID("6f1c2a4e-0000-4000-8000-a5605a5605a5")
THR = Thresholds(low=0.4, high=0.7)


def uid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def sha(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- edge


def events() -> list[Event]:
    def frame(i: int, cam="CAM-01") -> FrameMeta:
        return FrameMeta(
            frame_id=f"{cam}-{i:06d}", timestamp=at(170 + i), workstation_id="WS-01", camera_id=cam
        )

    return [
        Event(
            use_case=UseCase.QUALITY,
            score=0.82,
            latency_ms=4.1,
            model_name="argos-quality",
            model_version="3",
            details=QualityDetails(
                zones=[AnomalyZone(bbox=BBox(x1=0.21, y1=0.3, x2=0.42, y2=0.55), score=0.82)]
            ),
            event_id=uid("ev-q"),
            frame=FrameMeta(
                frame_id="cycle:WS-01:C-20261126-000412",
                timestamp=at(172),
                workstation_id="WS-01",
                camera_id="CAM-Q",
            ),
            decision=Decision.ANOMALIE,
            thresholds_used=THR,
        ),
        Event(
            use_case=UseCase.WORKSTATION,
            score=0.55,
            latency_ms=11.0,
            model_name="fake-workstation",
            model_version="0.1.0",
            details=WorkstationDetails(
                expected=["screwdriver", "gauge", "torque_wrench"],
                detected=[
                    DetectedObject(
                        label="screwdriver",
                        confidence=0.93,
                        bbox=BBox(x1=0.05, y1=0.7, x2=0.2, y2=0.85),
                    )
                ],
                missing=["gauge"],
                misplaced=["torque_wrench"],
            ),
            event_id=uid("ev-w"),
            frame=frame(1),
            decision=Decision.A_VERIFIER,
            thresholds_used=THR,
            operator_feedback=OperatorFeedback(
                verdict="defaut", comment="jauge absente", at=at(172)
            ),
        ),
        Event(
            use_case=UseCase.SAFETY,
            score=0.91,
            latency_ms=18.5,
            model_name="mock-ppe+mock-behavior",
            model_version="0.1.0+0.1.0",
            details=SafetyDetails(
                person_count=1,
                persons=[
                    PersonPPE(
                        person_index=0,
                        bbox=BBox(x1=0.6, y1=0.1, x2=0.85, y2=0.95),
                        helmet=PPEState.ABSENT,
                        vest=PPEState.PRESENT,
                        glasses=PPEState.UNCERTAIN,
                        gloves=PPEState.PRESENT,
                        phone=True,
                    )
                ],
            ),
            event_id=uid("ev-s"),
            frame=frame(2),
            decision=Decision.ANOMALIE,
            thresholds_used=THR,
        ),
    ]


def prediction(verdict: PartVerdict, decision: Decision, score: float, name: str) -> AIPrediction:
    return AIPrediction(
        verdict=verdict,
        ai_decision=decision,
        score=score,
        model_name="argos-quality",
        model_version="3",
        thresholds_used=THR,
        event_id=uid(f"ev-{name}"),
        latency_ms=4.2,
    )


SHIFT = Shift(
    shift_id=uid("shift-ws01"),
    station_id="WS-01",
    name="matin",
    status="OPEN",
    started_at=T0,
    planned_duration_min=480,
    target_parts=400,
)


def parts() -> list[Part]:
    base = dict(
        station_id="WS-01",
        shift_id=SHIFT.shift_id,
        trigger_source="plc",
        camera_id="CAM-Q",
        correction_count=0,
    )
    return [
        Part(
            part_id=uid("p-err"),
            cycle_id="C-20261126-000413",
            created_at=at(173),
            image_sha256=None,
            predicted_verdict="ERROR",
            prediction=None,
            error=InferenceError(
                code=ErrorCode.CAPTURE_FAILED, message="no image received for an industrial cycle"
            ),
            effective_verdict="ERROR",
            **base,
        ),
        Part(
            part_id=uid("p-nok"),
            cycle_id="C-20261126-000412",
            created_at=at(172),
            image_sha256=sha("img-412"),
            predicted_verdict="NOK",
            prediction=prediction(PartVerdict.NOK, Decision.ANOMALIE, 0.82, "q"),
            error=None,
            effective_verdict="OK",
            **{**base, "correction_count": 1},
        ),
        Part(
            part_id=uid("p-hold"),
            cycle_id="C-20261126-000411",
            created_at=at(171),
            image_sha256=sha("img-411"),
            predicted_verdict="HOLD",
            prediction=prediction(PartVerdict.HOLD, Decision.A_VERIFIER, 0.52, "hold"),
            error=None,
            effective_verdict="HOLD",
            **base,
        ),
        Part(
            part_id=uid("p-ok"),
            cycle_id="C-20261126-000410",
            created_at=at(170),
            image_sha256=sha("img-410"),
            predicted_verdict="OK",
            prediction=prediction(PartVerdict.OK, Decision.CONFORME, 0.08, "ok"),
            error=None,
            effective_verdict="OK",
            disposition="SHIPPED",
            disposition_updated_at=at(175),
            **base,
        ),
    ]


def corrections() -> list[Correction]:
    return [
        Correction(
            correction_id=uid("c1"),
            part_id=uid("p-nok"),
            sequence=1,
            previous_verdict="NOK",
            new_verdict="OK",
            reason="Pièce vérifiée conforme, faux rejet (reflet)",
            actor_role="operator",
            physical_inspection=True,
            at=at(174),
        ),
    ]


def shift_report(
    shift: Shift, ok: int, nok: int, hold: int, error: int, corrected: int, now: datetime = NOW
) -> ShiftReport:
    tally = Tally(
        effective={
            PartVerdict.OK: ok,
            PartVerdict.NOK: nok,
            PartVerdict.HOLD: hold,
            PartVerdict.ERROR: error,
        },
        predicted={
            PartVerdict.OK: ok - corrected,
            PartVerdict.NOK: nok + corrected,
            PartVerdict.HOLD: hold,
            PartVerdict.ERROR: error,
        },
        corrected=corrected,
        mean_latency_ms=4.3,
    )
    kpi = compute_kpi(
        tally,
        window_start=shift.started_at,
        window_end=shift.ended_at or now,
        now=now,
        target_parts=shift.target_parts,
        planned_duration_min=shift.planned_duration_min,
    )
    return ShiftReport(shift=shift, kpi=kpi)


def station_kpi() -> ProductionKPI:
    return shift_report(SHIFT, 131, 9, 2, 1, 3).kpi


def edge_fixtures() -> dict[str, tuple[Any, Any]]:
    ev = events()
    return {
        "edge/health": (
            dict[str, Any],
            {
                "status": "ok",
                "version": __version__,
                "device": "cpu",
                "source": "synthetic",
                "pipeline_running": True,
                "frames_processed": 1234,
                "pipeline_error": None,
            },
        ),
        "edge/use-cases": (
            list[UseCaseInfo],
            [
                UseCaseInfo(
                    use_case=uc,
                    status="ok",
                    analyzer_class=cls,
                    name=name,
                    version=version,
                    thresholds=THR,
                )
                for uc, cls, name, version in [
                    (
                        UseCase.QUALITY,
                        "usecases.quality.analyzer:FakeQualityAnalyzer",
                        "fake-quality",
                        "0.1.0",
                    ),
                    (
                        UseCase.WORKSTATION,
                        "usecases.workstation.analyzer:FakeWorkstationAnalyzer",
                        "fake-workstation",
                        "0.1.0",
                    ),
                    (
                        UseCase.SAFETY,
                        "usecases.safety.analyzer:FakeSafetyAnalyzer",
                        "fake-safety",
                        "0.1.0",
                    ),
                ]
            ],
        ),
        "edge/events": (list[Event], ev),
        "edge/stats": (
            Stats,
            Stats(
                by_use_case={
                    "quality": UseCaseStats(
                        counts={"conforme": 120, "a_verifier": 6, "anomalie": 9}, pending_review=2
                    ),
                    "workstation": UseCaseStats(
                        counts={"conforme": 300, "a_verifier": 12, "anomalie": 4}, pending_review=5
                    ),
                    "safety": UseCaseStats(
                        counts={"conforme": 280, "a_verifier": 20, "anomalie": 7}, pending_review=8
                    ),
                }
            ),
        ),
        "edge/production-parts": (list[Part], parts()),
        "edge/production-part-corrections": (list[Correction], corrections()),
        "edge/production-shift-current": (ShiftReport, shift_report(SHIFT, 131, 9, 2, 1, 3)),
        "edge/production-kpi": (ProductionKPI, station_kpi()),
    }


# --------------------------------------------------------------------------- core / mlops


def model_ref(use_case: UseCase, version: str = "3") -> ModelRef:
    return ModelRef(
        registered_model=f"argos-{use_case.value}",
        version=version,
        alias="champion",
        mlflow_run_id=uid(f"run-{use_case}-{version}")[:32],
    )


def dataset(use_case: UseCase) -> DatasetRef:
    if use_case == UseCase.QUALITY:
        return DatasetRef(
            name="ref-part-a",
            version="v1.0",
            uri="dvc://argos/datasets/ref-part-a",
            manifest_sha256=sha("ds-ref-part-a"),
            num_samples=1000,
            splits={"train": 700, "val": 150, "test": 150},
            split_strategy="by_sequence",
            classes=["OK", "NOK"],
        )
    return DatasetRef(
        name=f"{use_case.value}-synthetic",
        version="v0.1",
        uri=f"dvc://argos/datasets/{use_case.value}",
        manifest_sha256=sha(use_case),
        num_samples=0,
        split_strategy="by_time",
        confidential=False,
    )


def evaluation(use_case: UseCase) -> EvaluationMetrics:
    metrics = {"recall_nok": 0.991, "false_reject_rate": 0.043, "accuracy": 0.968}
    return EvaluationMetrics(
        mlflow_run_id=model_ref(use_case).mlflow_run_id,
        dataset=dataset(use_case),
        metrics=metrics,
        confusion_matrix=[[118, 5], [1, 102]],
        class_order=["OK", "NOK"],
        recommended_thresholds=Thresholds(low=0.3, high=0.6),
        latency_ms_p50_cpu=3.8,
        latency_ms_p95_cpu=6.1,
    )


def package(use_case: UseCase) -> ModelPackage:
    classes = {
        UseCase.QUALITY: ["OK", "NOK"],
        UseCase.SAFETY: ["person", "helmet", "vest", "glasses", "gloves", "phone"],
        UseCase.WORKSTATION: ["screwdriver", "gauge", "torque_wrench"],
    }[use_case]
    return ModelPackage(
        use_case=use_case,
        model=model_ref(use_case),
        analyzer_class=f"usecases.{use_case.value}.analyzer:OnnxAnalyzer",
        runtime="onnxruntime",
        artifact=ArtifactRef(
            uri="model.onnx", sha256=sha(f"onnx-{use_case}"), size_bytes=6_291_456, format="onnx"
        ),
        preprocessing=PreprocessingSpec(
            input_size=(224, 224) if use_case == UseCase.QUALITY else (640, 640),
            color="RGB",
            resize="letterbox",
        ),
        classes=classes,
        thresholds=Thresholds(low=0.3, high=0.6),
        params={"top_k": 1},
        dataset=dataset(use_case),
        evaluation=evaluation(use_case) if use_case == UseCase.QUALITY else None,
        created_at=T0 - timedelta(days=1),
    )


STATIONS = [f"WS-{i:02d}" for i in range(1, 13)]


def stations() -> list[StationSummary]:
    out = []
    for i, station in enumerate(STATIONS):
        rng = random.Random(station)
        online = station != "WS-09"
        shift = Shift(
            shift_id=uid(f"shift-{station}"),
            station_id=station,
            name="matin",
            status="OPEN",
            started_at=T0,
            planned_duration_min=480,
            target_parts=400,
        )
        ok, nok = rng.randint(100, 150), rng.randint(0, 15)
        report = (
            shift_report(shift, ok, nok, rng.randint(0, 4), rng.randint(0, 2), rng.randint(0, 3))
            if online
            else None
        )
        camera_status = "degraded" if station == "WS-07" else ("down" if not online else "ok")
        out.append(
            StationSummary(
                station_id=station,
                name=f"Poste {i + 1:02d}",
                cell="ABC"[i // 4],
                simulated=station != "WS-01",
                online=online,
                last_seen_at=NOW if online else T0 + timedelta(minutes=95),
                current_shift=report,
                equipment=[
                    EquipmentStatusPayload(
                        equipment_id=f"{station}-CAM-Q",
                        equipment_type="camera",
                        status=camera_status,
                    ),
                    EquipmentStatusPayload(
                        equipment_id=f"{station}-PLC",
                        equipment_type="plc",
                        status="ok" if online else "unknown",
                    ),
                ],
                models=[
                    StationDeploymentStatus(
                        station_id=station,
                        use_case=UseCase.QUALITY,
                        status="loaded" if online else "absent",
                        model=model_ref(UseCase.QUALITY) if online else None,
                        package_sha256=sha(f"onnx-{UseCase.QUALITY}"),
                        loaded_at=T0 if online else None,
                    )
                ],
                open_alerts=sum(
                    1
                    for a in alerts()
                    if a.station_id == station and a.status in ("open", "acknowledged")
                ),
            )
        )
    return out


def alerts() -> list[Alert]:
    specs = [
        ("WS-01", UseCase.SAFETY, "ppe.helmet_missing", "critical", "open", "Casque absent"),
        (
            "WS-03",
            UseCase.SAFETY,
            "behavior.phone_use",
            "warning",
            "acknowledged",
            "Utilisation du téléphone",
        ),
        (
            "WS-05",
            UseCase.SAFETY,
            "behavior.hand_in_danger_zone",
            "critical",
            "open",
            "Main dans la zone presse",
        ),
        ("WS-07", None, "equipment.camera_degraded", "warning", "open", "Caméra qualité dégradée"),
        (
            "WS-02",
            UseCase.WORKSTATION,
            "workstation.missing_object",
            "info",
            "validated",
            "Jauge manquante",
        ),
        (
            "WS-11",
            UseCase.QUALITY,
            "quality.nok_burst",
            "warning",
            "rejected",
            "Série de NOK (5 en 10 min)",
        ),
    ]
    return [
        Alert(
            alert_id=uid(f"alert-{i}"),
            station_id=s,
            camera_id=f"{s}-CAM-01",
            use_case=uc,
            alert_type=t,
            severity=sev,
            status=st,
            title=title,
            first_seen_at=at(150 + i),
            last_seen_at=at(160 + 2 * i),
            occurrences=3 + i,
            max_score=0.7 + i / 50,
            source_event_ids=[uid(f"alert-{i}-ev")],
            simulated=s != "WS-01",
        )
        for i, (s, uc, t, sev, st, title) in enumerate(specs)
    ]


def operator_reports() -> list[OperatorReport]:
    return [
        OperatorReport(
            report_id=uid("r1"),
            station_id="WS-01",
            created_at=at(165),
            category="quality",
            severity="warning",
            message="Beaucoup de rejets sur la pièce de référence depuis 7 h",
            related_part_id=uid("p-nok"),
        ),
        OperatorReport(
            report_id=uid("r2"),
            station_id="WS-04",
            created_at=at(120),
            category="equipment",
            severity="critical",
            message="Éclairage du poste instable",
            status="acknowledged",
        ),
    ]


def mlops_fixtures() -> dict[str, tuple[Any, Any]]:
    q = UseCase.QUALITY
    config = TrainingConfig(
        use_case=q,
        task="classification",
        architecture="yolo26n-cls",
        base_weights="yolo26n-cls.pt",
        image_size=(224, 224),
        epochs=50,
        batch_size=64,
        seed=42,
        hyperparameters={"lr0": 0.001},
        dataset=dataset(q),
    )
    return {
        "core/models": (list[ModelPackage], [package(uc) for uc in UseCase]),
        "core/deployments": (
            list[ModelDeployment],
            [
                ModelDeployment(
                    deployment_id=uid("d1"),
                    station_id="WS-01",
                    use_case=q,
                    model=model_ref(q),
                    package_sha256=sha(f"onnx-{q}"),
                    status="active",
                    requested_at=T0 - timedelta(hours=20),
                    approved_at=T0 - timedelta(hours=19),
                    approved_by_role="ai_leader",
                    previous_model=model_ref(q, "2"),
                ),
                ModelDeployment(
                    deployment_id=uid("d2"),
                    station_id="WS-02",
                    use_case=q,
                    model=model_ref(q, "4"),
                    package_sha256=sha("onnx-v4"),
                    status="pending_approval",
                    requested_at=at(100),
                    previous_model=model_ref(q),
                ),
            ],
        ),
        "core/training-jobs": (
            list[TrainingJob],
            [
                TrainingJob(
                    job_id=uid("job-1"),
                    status="succeeded",
                    trigger="manual",
                    config=config,
                    mlflow_experiment_id="12",
                    mlflow_run_id=model_ref(q).mlflow_run_id,
                    compute="a100-cluster",
                    created_at=T0 - timedelta(days=2),
                    started_at=T0 - timedelta(days=2),
                    ended_at=T0 - timedelta(days=2, hours=-1),
                ),
                TrainingJob(
                    job_id=uid("job-2"),
                    status="running",
                    trigger="policy",
                    config=config,
                    mlflow_experiment_id="12",
                    compute="a100-cluster",
                    created_at=at(90),
                    started_at=at(92),
                ),
            ],
        ),
        "core/monitoring": (
            list[MonitoringMetrics],
            [
                MonitoringMetrics(
                    station_id=None,
                    use_case=q,
                    model=model_ref(q),
                    window_start=T0,
                    window_end=NOW,
                    n_inferences=1650,
                    decision_rates={"conforme": 0.9, "a_verifier": 0.04, "anomalie": 0.06},
                    mean_score=0.21,
                    latency_ms_p95=6.4,
                    human_agreement_rate=0.93,
                    drift=[
                        DriftMeasure(
                            feature="score", method="psi", value=0.08, threshold=0.2, alert=False
                        ),
                        DriftMeasure(
                            feature="brightness",
                            method="ks",
                            value=0.31,
                            threshold=0.25,
                            alert=True,
                        ),
                    ],
                )
            ],
        ),
        "core/retraining-policies": (
            list[RetrainingPolicy],
            [
                RetrainingPolicy(
                    use_case=q,
                    enabled=True,
                    min_new_labels=200,
                    max_drift_alerts=3,
                    min_human_agreement=0.9,
                    auto_train=True,
                ),
                RetrainingPolicy(use_case=UseCase.SAFETY),
            ],
        ),
    }


def edge_batch() -> EdgeEventBatch:
    ev = events()
    nok, correction = parts()[1], corrections()[0]
    common = dict(station_id="WS-01", simulated=False)
    items = [
        EdgeEvent(
            event_id=uid("ee-1"),
            event_type="shift.opened",
            edge_sequence=101,
            occurred_at=T0,
            payload=ShiftPayload(shift=SHIFT),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-2"),
            event_type="inference",
            edge_sequence=102,
            occurred_at=ev[0].frame.timestamp,
            camera_id="CAM-Q",
            cycle_id=nok.cycle_id,
            use_case=UseCase.QUALITY,
            model_name="argos-quality",
            model_version="3",
            score=0.82,
            decision=Decision.ANOMALIE,
            payload=InferencePayload(event=ev[0]),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-3"),
            event_type="part.recorded",
            edge_sequence=103,
            occurred_at=nok.created_at,
            camera_id="CAM-Q",
            cycle_id=nok.cycle_id,
            part_id=nok.part_id,
            use_case=UseCase.QUALITY,
            verdict=PartVerdict.NOK,
            payload=PartRecordedPayload(
                part=nok.model_copy(
                    update={"effective_verdict": PartVerdict.NOK, "correction_count": 0}
                )
            ),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-4"),
            event_type="part.corrected",
            edge_sequence=104,
            occurred_at=correction.at,
            cycle_id=nok.cycle_id,
            part_id=nok.part_id,
            verdict=PartVerdict.OK,
            payload=PartCorrectedPayload(correction=correction),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-5"),
            event_type="operator.report",
            edge_sequence=105,
            occurred_at=at(165),
            payload=OperatorReportPayload(
                **operator_reports()[0].model_dump(include=set(OperatorReportPayload.model_fields))
            ),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-6"),
            event_type="equipment.status",
            edge_sequence=106,
            occurred_at=at(166),
            camera_id="CAM-Q",
            payload=EquipmentStatusPayload(
                equipment_id="WS-01-CAM-Q", equipment_type="camera", status="ok"
            ),
            **common,
        ),
        EdgeEvent(
            event_id=uid("ee-7"),
            event_type="model.status",
            edge_sequence=107,
            occurred_at=at(1),
            use_case=UseCase.QUALITY,
            model_name="argos-quality",
            model_version="3",
            payload=ModelStatusPayload(
                use_case=UseCase.QUALITY,
                model_name="argos-quality",
                model_version="3",
                package_sha256=sha(f"onnx-{UseCase.QUALITY}"),
                loaded=True,
            ),
            **common,
        ),
    ]
    return EdgeEventBatch(station_id="WS-01", sent_at=NOW, events=items)


def build_fixtures() -> dict[str, tuple[Any, Any]]:
    batch = edge_batch()
    ack = IngestAck(
        station_id="WS-01",
        received_at=NOW + timedelta(seconds=1),
        results=[
            IngestResult(event_id=e.event_id, status="duplicate" if i == 0 else "accepted")
            for i, e in enumerate(batch.events)
        ],
        highest_contiguous_sequence=107,
    )
    return {
        **edge_fixtures(),
        "core/stations": (list[StationSummary], stations()),
        "core/alerts": (list[Alert], alerts()),
        "core/operator-reports": (list[OperatorReport], operator_reports()),
        **mlops_fixtures(),
        "integration/edge-event-batch": (EdgeEventBatch, batch),
        "integration/ingest-ack": (IngestAck, ack),
    }
