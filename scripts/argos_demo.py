"""Run a bounded, explicitly synthetic ARGOS dashboard demonstration.

Production facts always use the Production Engine HTTP API. Safety, workstation,
camera and offline facts use dedicated synthetic stations on the Core ingest API.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from visionhub.contracts import (
    Decision,
    Event,
    FrameMeta,
    PersonPPE,
    PPEState,
    QualityDetails,
    SafetyDetails,
    UseCase,
    WorkstationDetails,
)
from visionhub.core.simulator import THRESHOLDS
from visionhub.integration.edge_events import EdgeEvent, EdgeEventBatch, EdgeEventType, IngestAck

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = uuid.UUID("b4de50a0-62fb-4b38-bc3a-33be4e36337d")
SCENARIOS = ("normal", "quality", "multiple", "disconnect", "full")


def now_utc() -> datetime:
    return datetime.now(UTC)


def loopback_origin(url: str) -> str:
    parsed = urlsplit(url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port is None
    ):
        raise ValueError("Core and Edge URLs must be explicit localhost HTTP origins with ports")
    return url.rstrip("/")


def args_from(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("autonomous", "connected"), default="autonomous")
    parser.add_argument("--scenario", choices=SCENARIOS, default="full")
    parser.add_argument("--stations", type=int, default=12)
    parser.add_argument("--direct-stations", type=int, default=2)
    parser.add_argument(
        "--rate", type=float, default=2.0, help="total production cycles per second"
    )
    parser.add_argument(
        "--duration", type=float, default=60.0, help="maximum active run time, seconds"
    )
    parser.add_argument("--nok-rate", type=float, default=0.10, help="target, not a guarantee")
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--run-id")
    parser.add_argument("--core-port", type=int, default=18220)
    parser.add_argument("--edge-port", type=int, default=18240)
    parser.add_argument("--core-url")
    parser.add_argument("--edge-url")
    args = parser.parse_args(argv)
    args.run_id = args.run_id or uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9]{4,12}", args.run_id):
        parser.error("--run-id must have 4..12 letters or digits")
    if not 2 <= args.stations <= 50 or not 0 <= args.direct_stations < args.stations:
        parser.error("require 2..50 stations and 0 <= direct-stations < stations")
    if args.scenario in ("multiple", "full") and args.direct_stations < 2:
        parser.error("multiple and full scenarios need two direct synthetic stations")
    if args.scenario == "disconnect" and args.mode == "connected":
        parser.error("disconnect is reserved for autonomous mode")
    if args.rate <= 0 or args.duration < 4 or not 0 <= args.nok_rate <= 1:
        parser.error("require rate > 0, duration >= 4 seconds and nok-rate in [0,1]")
    if args.mode == "connected":
        if not args.core_url or not args.edge_url:
            parser.error("connected mode requires --core-url and --edge-url")
        try:
            args.core_url = loopback_origin(args.core_url)
            args.edge_url = loopback_origin(args.edge_url)
        except ValueError as exc:
            parser.error(str(exc))
    elif args.core_url or args.edge_url:
        parser.error("autonomous mode selects its own localhost ports")
    return args


def _port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class OwnedServers:
    """Own only the two children started by this demonstration."""

    def __init__(self, args: argparse.Namespace) -> None:
        if args.core_port == args.edge_port or not all(
            _port_available(port) for port in (args.core_port, args.edge_port)
        ):
            raise RuntimeError("demo ports are occupied; choose two free --core-port/--edge-port")
        self.core_url = f"http://127.0.0.1:{args.core_port}"
        self.edge_url = f"http://127.0.0.1:{args.edge_port}"
        self.directory = ROOT / "var" / "sim" / args.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.core: subprocess.Popen | None = None
        self.edge: subprocess.Popen | None = None
        self._logs = []
        self.core_env = {**os.environ, "ARGOS_CORE_DB": str(self.directory / "core.sqlite3")}
        self.edge_env = {
            **os.environ,
            "DB_PATH": str(self.directory / "edge.sqlite3"),
            "PIPELINE_ENABLED": "false",
            "ARGOS_CORE_URL": self.core_url,
            "SOURCE": "synthetic",
        }
        self.core_port = args.core_port
        self.edge_port = args.edge_port

    def _start(self, name: str, module: str, port: int, env: dict[str, str]) -> subprocess.Popen:
        log = (self.directory / f"{name}.log").open("a", encoding="utf-8")
        self._logs.append(log)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        url = f"http://127.0.0.1:{port}/health"
        with httpx.Client(timeout=1.0) as client:
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited during startup; see {log.name}")
                try:
                    if client.get(url).status_code == 200:
                        return process
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
        self._stop(process)
        raise RuntimeError(f"{name} did not start; see {log.name}")

    @staticmethod
    def _stop(process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def __enter__(self) -> OwnedServers:
        try:
            self.core = self._start("core", "visionhub.core.app:app", self.core_port, self.core_env)
            self.edge = self._start(
                "edge", "visionhub.argos_app:app", self.edge_port, self.edge_env
            )
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def stop_core(self) -> None:
        self._stop(self.core)
        self.core = None

    def restart_core(self) -> None:
        if self.core is not None:
            return
        self.core = self._start("core", "visionhub.core.app:app", self.core_port, self.core_env)

    def __exit__(self, *_exc: object) -> None:
        self._stop(self.edge)
        self._stop(self.core)
        for log in self._logs:
            log.close()


class DirectSynthetic:
    """A separate Core-only event stream for each reserved demo station."""

    def __init__(self, run_id: str, client: httpx.Client) -> None:
        self.run_id = run_id
        self.client = client
        self.sequences: dict[str, int] = {}
        self.pending: dict[str, list[EdgeEvent]] = {}
        self.accepted = 0
        self.duplicates = 0

    def add(
        self,
        station: str,
        kind: EdgeEventType,
        payload: object,
        *,
        occurred_at: datetime | None = None,
        **headers: object,
    ) -> EdgeEvent:
        sequence = self.sequences.get(station, 0) + 1
        self.sequences[station] = sequence
        event = EdgeEvent(
            event_id=str(uuid.uuid5(NAMESPACE, f"{self.run_id}:{station}:{sequence}")),
            station_id=station,
            edge_sequence=sequence,
            event_type=kind,
            occurred_at=occurred_at or now_utc(),
            simulated=True,
            payload=payload,
            **headers,
        )
        self.pending.setdefault(station, []).append(event)
        return event

    def equipment(self, station: str, equipment_id: str, status: str, when=None) -> None:
        self.add(
            station,
            EdgeEventType.EQUIPMENT_STATUS,
            {
                "kind": "equipment.status",
                "equipment_id": equipment_id,
                "equipment_type": "camera",
                "status": status,
                "detail": "SYNTHETIC DEMO; no physical camera was inspected",
            },
            occurred_at=when,
            camera_id="CAM-DEMO",
        )

    def incident(self, station: str, use_case: UseCase, index: int) -> None:
        stamp = now_utc()
        camera = {
            UseCase.SAFETY: "CAM-S",
            UseCase.WORKSTATION: "CAM-W",
            UseCase.QUALITY: "CAM-Q",
        }[use_case]
        if use_case == UseCase.SAFETY:
            details = SafetyDetails(
                person_count=1,
                persons=[
                    PersonPPE(
                        person_index=0,
                        helmet=PPEState.ABSENT,
                        vest=PPEState.PRESENT,
                        glasses=PPEState.PRESENT,
                        gloves=PPEState.PRESENT,
                        phone=False,
                    )
                ],
            )
        elif use_case == UseCase.WORKSTATION:
            details = WorkstationDetails(expected=["tool"], missing=["tool"])
        else:
            details = QualityDetails()
        finding = Event(
            event_id=str(
                uuid.uuid5(NAMESPACE, f"{self.run_id}:{station}:{use_case}:{index}:finding")
            ),
            frame=FrameMeta(
                frame_id=f"synthetic:{self.run_id}:{station}:{use_case}:{index}",
                timestamp=stamp,
                workstation_id=station,
                camera_id=camera,
            ),
            use_case=use_case,
            score=0.9,
            latency_ms=0,
            model_name="synthetic-demo-no-model",
            model_version="0",
            details=details,
            decision=Decision.ANOMALIE,
            thresholds_used=THRESHOLDS,
        )
        self.add(
            station,
            EdgeEventType.INFERENCE,
            {"kind": "inference", "event": finding},
            occurred_at=stamp,
            camera_id=camera,
            use_case=use_case,
            score=finding.score,
            decision=finding.decision,
            model_name=finding.model_name,
            model_version=finding.model_version,
        )

    def flush(self) -> None:
        for station, events in list(self.pending.items()):
            if not events:
                continue
            batch = EdgeEventBatch(station_id=station, sent_at=now_utc(), events=events[:500])
            try:
                response = self.client.post("/ingest/v1/events", json=batch.model_dump(mode="json"))
                response.raise_for_status()
                ack = IngestAck.model_validate(response.json())
            except (httpx.HTTPError, ValueError):
                continue  # Keep the identical in-memory batch for retry after Core recovers.
            if ack.station_id != station or [r.event_id for r in ack.results] != [
                e.event_id for e in batch.events
            ]:
                raise RuntimeError("Core ACK differs from synthetic batch")
            for result in ack.results:
                if result.status == "rejected":
                    raise RuntimeError(
                        f"Core rejected synthetic event {result.event_id}: {result.error}"
                    )
                self.accepted += result.status == "accepted"
                self.duplicates += result.status == "duplicate"
            del events[: len(batch.events)]


class FakeInputSelector:
    """Select cycle IDs using the existing fake analyzer, without changing a model."""

    def __init__(self) -> None:
        import numpy as np

        from usecases.quality.analyzer import FakeQualityAnalyzer

        self.analyzer = FakeQualityAnalyzer()
        self.analyzer.load(
            {"seed": 42, "anomaly_rate": 0.08, "min_latency_ms": 0, "max_latency_ms": 0}
        )
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)

    def choose(self, station: str, run_id: str, number: int, want_nok: bool) -> str:
        for candidate in range(1, 257):
            cycle_id = f"D{run_id}-{number:05d}-{candidate:03d}"
            meta = FrameMeta(
                frame_id=f"cycle:{station}:{cycle_id}",
                workstation_id=station,
                camera_id="CAM-Q",
            )
            score = self.analyzer.analyze(self.image, meta).score
            if (score >= 0.7) == want_nok and (want_nok or score < 0.4):
                return cycle_id
        raise RuntimeError("fake analyzer could not select a matching synthetic input")


def _json(response: httpx.Response) -> object:
    response.raise_for_status()
    return response.json()


def check_collision(core: httpx.Client, edge: httpx.Client, stations: list[str]) -> None:
    existing = {item["station_id"] for item in _json(core.get("/api/v1/stations"))}
    for station in stations:
        if station in existing:
            raise RuntimeError(f"simulation station already exists in Core: {station}")
        if _json(edge.get("/production/parts", params={"station_id": station, "limit": 1})):
            raise RuntimeError(f"simulation station already has an Edge part: {station}")
        if _json(edge.get("/production/shifts", params={"station_id": station, "limit": 1})):
            raise RuntimeError(f"simulation station already has an Edge shift: {station}")


def snapshot(core: httpx.Client, run_id: str, target: float) -> dict | None:
    try:
        prefix = f"SIM{run_id.upper()}-"
        stations = [
            s for s in _json(core.get("/api/v1/stations")) if s["station_id"].startswith(prefix)
        ]
        kpis = [
            _json(core.get(f"/api/v1/stations/{station['station_id']}/kpi")) for station in stations
        ]
        parts = sum(kpi["total_parts"] for kpi in kpis)
        nok = sum(kpi["nok_parts"] for kpi in kpis)
        alerts = [
            a for a in _json(core.get("/api/v1/alerts")) if a["station_id"].startswith(prefix)
        ]
    except httpx.HTTPError:
        return None
    result = {
        "stations": len(stations),
        "offline": sum(not s["online"] for s in stations),
        "parts": parts,
        "nok": nok,
        "observed_nok_rate": round(nok / parts, 3) if parts else None,
        "target_nok_rate": target,
        "open_alerts": sum(a["status"] in ("open", "acknowledged", "validated") for a in alerts),
        "alerts": len(alerts),
        "resolved_alerts": sum(a["status"] == "resolved" for a in alerts),
        "max_alert_occurrences": max((a["occurrences"] for a in alerts), default=0),
    }
    print("KPI", json.dumps(result, ensure_ascii=False), flush=True)
    return result


def resolve_incidents(core: httpx.Client, stations: list[str]) -> int:
    count = 0
    for alert in _json(core.get("/api/v1/alerts")):
        if alert["station_id"] not in stations or not alert["simulated"]:
            continue
        if alert["status"] in ("open", "acknowledged", "validated"):
            _json(core.post(f"/api/v1/alerts/{alert['alert_id']}/resolve"))
            count += 1
    return count


def run(args: argparse.Namespace, owned: OwnedServers | None = None) -> dict:
    core_url = owned.core_url if owned else args.core_url
    edge_url = owned.edge_url if owned else args.edge_url
    prefix = f"SIM{args.run_id.upper()}"
    stations = [f"{prefix}-{i:02d}" for i in range(1, args.stations + 1)]
    production = stations[: args.stations - args.direct_stations]
    direct = stations[len(production) :]
    rng = random.Random(args.seed)
    parts: list[dict] = []
    correction = None
    incident_sent = resolved = disconnected = reconnected = False
    quality_burst_count = 0
    with (
        httpx.Client(base_url=core_url, timeout=2.0) as core,
        httpx.Client(base_url=edge_url, timeout=5.0) as edge,
    ):
        check_collision(core, edge, stations)
        quality = next(
            (item for item in _json(edge.get("/use-cases")) if item["use_case"] == "quality"),
            None,
        )
        selector = FakeInputSelector() if quality and quality["name"] == "fake-quality" else None
        print(
            f"SYNTHETIC DEMO {args.run_id}: "
            f"{len(production)} Edge + {len(direct)} Core-only stations",
            flush=True,
        )
        emitter = DirectSynthetic(args.run_id, core)
        for index, station in enumerate(direct):
            stale = args.scenario == "full" and index == 0
            emitter.equipment(
                station,
                f"{station}-CAM-DEMO",
                "ok",
                now_utc() - timedelta(minutes=10) if stale else None,
            )
        emitter.flush()
        target_per_station = max(1, int(args.rate * args.duration / len(production)) + 1)
        for station in production:
            _json(
                edge.post(
                    f"/production/stations/{station}/shifts",
                    json={"name": f"SIM-{args.run_id}", "target_parts": target_per_station},
                )
            )
        started = time.monotonic()
        deadline = started + args.duration
        next_cycle = started
        next_report = started
        count = 0
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            phase = elapsed / args.duration
            if args.scenario in ("multiple", "full") and phase >= 0.2 and not incident_sent:
                for index in range(3):
                    emitter.incident(direct[0], UseCase.SAFETY, index)
                for index in range(2):
                    emitter.incident(direct[1], UseCase.WORKSTATION, index)
                emitter.equipment(direct[1], f"{direct[1]}-CAM-DEMO", "down")
                incident_sent = True
                print("SYNTHETIC Safety, Workstation and camera incidents", flush=True)
            if (
                args.scenario in ("quality", "multiple", "full")
                and phase >= 0.5
                and correction is None
                and parts
            ):
                if not any(p["predicted_verdict"] == "NOK" for p in parts) and direct:
                    emitter.incident(direct[0], UseCase.QUALITY, 0)
                    print("SYNTHETIC quality alert fallback on Core-only station", flush=True)
                selected = next(
                    (p for p in reversed(parts) if p["predicted_verdict"] == "NOK"), parts[-1]
                )
                new = "OK" if selected["effective_verdict"] == "NOK" else "NOK"
                correction = _json(
                    edge.post(
                        f"/production/parts/{selected['part_id']}/corrections",
                        json={
                            "new_verdict": new,
                            "expected_current_verdict": selected["effective_verdict"],
                            "reason": "SYNTHETIC demo physical inspection",
                            "actor_role": "operator",
                            "physical_inspection": True,
                        },
                    )
                )
                print(f"SYNTHETIC correction {selected['part_id']} -> {new}", flush=True)
            if (
                args.scenario in ("disconnect", "full")
                and owned
                and phase >= 0.58
                and not disconnected
            ):
                owned.stop_core()
                disconnected = True
                print("SYNTHETIC Core outage: only the owned Core process was stopped", flush=True)
            if disconnected and not reconnected and phase >= 0.76:
                owned.restart_core()
                reconnected = True
                print("Core restarted; Edge outbox will replay", flush=True)
            if time.monotonic() >= next_cycle:
                quality_burst = (
                    args.scenario in ("quality", "multiple", "full")
                    and 0.20 <= phase < 0.48
                    and quality_burst_count < 3
                )
                station = (
                    production[min(1, len(production) - 1)]
                    if quality_burst
                    else production[count % len(production)]
                )
                want_nok = quality_burst or rng.random() < args.nok_rate
                cycle_id = (
                    selector.choose(station, args.run_id, count + 1, want_nok)
                    if selector
                    else f"D{args.run_id}-{count + 1:05d}"
                )
                part = _json(
                    edge.post(
                        f"/production/stations/{station}/cycles",
                        data={"cycle_id": cycle_id, "camera_id": "CAM-Q", "simulated": "true"},
                    )
                )
                parts.append(part)
                quality_burst_count += int(quality_burst)
                count += 1
                next_cycle += 1 / args.rate
            if (
                incident_sent
                and args.scenario in ("multiple", "full")
                and phase >= 0.82
                and not resolved
                and (not disconnected or reconnected)
            ):
                emitter.equipment(direct[1], f"{direct[1]}-CAM-DEMO", "ok")
                emitter.flush()
                resolved_count = resolve_incidents(core, stations)
                resolved = True
                print(f"SYNTHETIC incident resolution: {resolved_count} alert(s)", flush=True)
            emitter.flush()
            if time.monotonic() >= next_report and (not disconnected or reconnected):
                snapshot(core, args.run_id, args.nok_rate)
                next_report += max(1.0, args.duration / 10)
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        if disconnected and not reconnected and owned:
            owned.restart_core()
        if incident_sent and not resolved:
            emitter.equipment(direct[1], f"{direct[1]}-CAM-DEMO", "ok")
            emitter.flush()
            resolved_count = resolve_incidents(core, stations)
            resolved = True
            print(f"SYNTHETIC incident resolution: {resolved_count} alert(s)", flush=True)
        for station in production:
            current = _json(edge.get(f"/production/stations/{station}/shifts/current"))
            _json(edge.post(f"/production/shifts/{current['shift']['shift_id']}/close"))
        drain_deadline = time.monotonic() + 12
        while time.monotonic() < drain_deadline:
            emitter.flush()
            status = _json(edge.get("/edge/sync/status"))
            if status["pending"] == 0 and not any(emitter.pending.values()):
                break
            time.sleep(0.25)
        status = _json(edge.get("/edge/sync/status"))
        final = snapshot(core, args.run_id, args.nok_rate)
        if final is None:
            raise RuntimeError("Core was unavailable at the end of the demonstration")
        final.update(
            run_id=args.run_id,
            mode=args.mode,
            scenario=args.scenario,
            production_stations=len(production),
            direct_stations=len(direct),
            produced_cycles=len(parts),
            observed_predicted_nok=sum(p["predicted_verdict"] == "NOK" for p in parts),
            predicted_nok_rate=round(
                sum(p["predicted_verdict"] == "NOK" for p in parts) / len(parts), 3
            )
            if parts
            else None,
            corrections=bool(correction),
            direct_accepted=emitter.accepted,
            direct_duplicates=emitter.duplicates,
            edge_pending_global=status["pending"],
            edge_rejected_global=status["rejected"],
        )
        print("FINAL", json.dumps(final, ensure_ascii=False), flush=True)
        if final["parts"] != len(parts):
            raise RuntimeError("Core part count differs from the cycles produced by this run")
        if any(emitter.pending.values()):
            raise RuntimeError("synthetic Core-only events remain unacknowledged")
        if owned and (status["pending"] or status["rejected"]):
            raise RuntimeError("dedicated Edge outbox contains unacknowledged events")
        return final


def main(argv: list[str] | None = None) -> int:
    args = args_from(argv)
    try:
        if args.mode == "autonomous":
            with OwnedServers(args) as owned:
                run(args, owned)
        else:
            run(args)
    except KeyboardInterrupt:
        print("SYNTHETIC DEMO interrupted cleanly", flush=True)
        return 130
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        print(f"SYNTHETIC DEMO failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
