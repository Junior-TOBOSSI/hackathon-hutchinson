"""Run the full demo WITHOUT Docker: API + dashboard, in two sub-processes.

    python -m visionhub.demo

Stop with Ctrl+C. Works the same on Windows, macOS and Linux.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from visionhub.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def wait_for_api(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    settings = Settings()
    for name, port in (
        ("API_PORT", settings.api_port),
        ("DASHBOARD_PORT", settings.dashboard_port),
    ):
        if not port_is_free(port):
            print(
                f"Port {port} is already in use by another program. "
                f"Choose another one, e.g. {name}={port + 10} in .env",
                file=sys.stderr,
            )
            return 1
    api_url = f"http://127.0.0.1:{settings.api_port}"
    # The dashboard does not import visionhub: it gets its settings through the environment.
    env = {
        **os.environ,
        "API_URL": api_url,
        "DASHBOARD_REFRESH_SECONDS": str(settings.dashboard_refresh_seconds),
    }

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "visionhub.api:app",
         "--host", settings.api_host, "--port", str(settings.api_port)],
        cwd=ROOT, env=env,
    )  # fmt: skip
    if not wait_for_api(api_url):
        print("The API did not start, see the logs above.", file=sys.stderr)
        api.terminate()
        return 1

    dashboard = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
         "--server.port", str(settings.dashboard_port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env=env,
    )  # fmt: skip

    print(
        f"\n  API        : {api_url}/docs"
        f"\n  Dashboard  : http://localhost:{settings.dashboard_port}"
        "\n  Ctrl+C to stop.\n",
        flush=True,
    )
    try:
        while api.poll() is None and dashboard.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (dashboard, api):
            if process.poll() is None:
                process.terminate()
        for process in (dashboard, api):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
