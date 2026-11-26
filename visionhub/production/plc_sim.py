"""Simulated PLC: triggers quality cycles on an ARGOS station through the REST API.

    python -m visionhub.production.plc_sim --api-url http://127.0.0.1:8000 --station WS-01

Every cycle is sent with ``simulated=true``: the server marks the parts
``trigger_source="plc_simulated"`` and draws a synthetic image for them. Cycle ids look
like ``SIM-<run id>-<counter>``; the run id combines the UTC start time and random bits,
so ids stay unique across restarts of the simulator. ``--duplicate-rate`` re-sends an
already sent cycle to demonstrate idempotence (the seed only drives these duplicates).
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
import time
from collections import Counter
from datetime import UTC, datetime

import httpx


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%S}{secrets.token_hex(4).upper()}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ARGOS simulated PLC")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--station", default="WS-01")
    parser.add_argument("--camera", default="CAM-Q")
    parser.add_argument("--interval", type=float, default=2.0, help="seconds between cycles")
    parser.add_argument("--cycles", type=int, default=20, help="number of new cycles (0 = endless)")
    parser.add_argument("--duplicate-rate", type=float, default=0.1, help="share of re-sent cycles")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0.0 <= args.duplicate_rate < 1.0:
        parser.error("--duplicate-rate must be in [0, 1)")
    return args


def run(args: argparse.Namespace, client: httpx.Client, sleep=time.sleep) -> Counter:
    rng = random.Random(args.seed)
    run_id = new_run_id()
    url = f"/production/stations/{args.station}/cycles"
    sent: list[str] = []
    stats: Counter = Counter()
    print(f"Simulated PLC run {run_id} -> {args.api_url}{url}", flush=True)
    while args.cycles == 0 or len(sent) < args.cycles:
        if sent and rng.random() < args.duplicate_rate:
            cycle_id, kind = rng.choice(sent), "duplicate"
        else:
            cycle_id, kind = f"SIM-{run_id}-{len(sent) + 1:06d}", "new"
            sent.append(cycle_id)
        data = {"cycle_id": cycle_id, "camera_id": args.camera, "simulated": "true"}
        try:
            response = client.post(url, data=data)
        except httpx.HTTPError as exc:
            stats["unreachable"] += 1
            print(f"{cycle_id:<34} API unreachable: {exc}", flush=True)
        else:
            if response.status_code in (200, 201):
                part = response.json()
                replay = response.headers.get("Idempotent-Replay") == "true"
                if replay:
                    stats["replayed"] += 1
                else:
                    stats["new"] += 1
                    stats[part["predicted_verdict"]] += 1
                print(
                    f"{cycle_id:<34} {kind:<9} -> {response.status_code} "
                    f"{part['predicted_verdict']:<5} {'(replay)' if replay else ''}",
                    flush=True,
                )
            else:
                stats[f"http_{response.status_code}"] += 1
                print(f"{cycle_id:<34} {kind:<9} -> {response.status_code} {response.text}")
        sleep(args.interval)
    return stats


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with httpx.Client(base_url=args.api_url, timeout=30) as client:
            stats = run(args, client)
    except KeyboardInterrupt:
        return 0
    print("Summary:", dict(stats), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
