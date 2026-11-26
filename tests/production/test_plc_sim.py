from fastapi.testclient import TestClient

from visionhub.argos_app import create_argos_app
from visionhub.config import Settings
from visionhub.production import plc_sim


def args(*extra):
    return plc_sim.parse_args(["--interval", "0", *extra])


def test_simulated_cycles_and_duplicates(tmp_path):
    settings = Settings(_env_file=None, db_path=str(tmp_path / "a.db"), pipeline_enabled=False)
    with TestClient(create_argos_app(settings)) as client:
        stats = plc_sim.run(
            args("--cycles", "15", "--duplicate-rate", "0.4", "--seed", "3"), client
        )
        assert stats["new"] == 15 and stats["replayed"] > 0
        assert sum(stats[v] for v in ("OK", "NOK", "HOLD", "ERROR")) == 15
        parts = client.get("/production/parts", params={"limit": 100}).json()
        assert len(parts) == 15  # duplicates created nothing
        assert all(p["trigger_source"] == "plc_simulated" for p in parts)
        assert all(p["cycle_id"].startswith("SIM-") for p in parts)

        # A second run never reuses the ids of the first one.
        stats = plc_sim.run(args("--cycles", "5", "--duplicate-rate", "0"), client)
        assert stats["new"] == 5 and stats["replayed"] == 0
        assert len(client.get("/production/parts", params={"limit": 100}).json()) == 20


def test_run_ids_are_unique():
    assert len({plc_sim.new_run_id() for _ in range(50)}) == 50


def test_unreachable_api_does_not_loop_forever():
    import httpx

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(base_url="http://plc.invalid", transport=httpx.MockTransport(refuse))
    stats = plc_sim.run(args("--cycles", "3"), client)
    assert stats["unreachable"] >= 3 and stats["new"] == 0
