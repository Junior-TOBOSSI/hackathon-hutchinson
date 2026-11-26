"""Configuration of the ARGOS MLOps tools, read from environment variables.

Nothing is hard-coded elsewhere: every script and the connector take a ``MlflowSettings``.

| Variable                              | Default                                   |
|---------------------------------------|-------------------------------------------|
| ``MLFLOW_TRACKING_URI``               | ``http://127.0.0.1:5000``                 |
| ``MLFLOW_REGISTRY_URI``               | same as the tracking URI                  |
| ``ARGOS_MLOPS_HOME``                  | ``%USERPROFILE%\\ARGOS_MLOPS_LOCAL``      |
| ``ARGOS_MLOPS_DOWNLOAD_DIR``          | ``<ARGOS_MLOPS_HOME>\\downloads``         |
| ``MLFLOW_HTTP_REQUEST_TIMEOUT``       | ``10`` seconds (MLflow's own variable)    |
| ``MLFLOW_HTTP_REQUEST_MAX_RETRIES``   | ``2`` (MLflow's own variable)             |
| ``MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR``| ``1`` (integer, MLflow's own variable)    |

The three ``MLFLOW_HTTP_*`` variables are read by the MLflow client at each request; the
connector sets them for its own process only (never in the Windows environment).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TRACKING_URI = "http://127.0.0.1:5000"

DEMO_EXPERIMENT = "argos-foundation-demo"
DEMO_MODEL = "argos-foundation-demo-model"
# Registry write operations of the connector are restricted to names with this prefix.
DEMO_PREFIX = "argos-foundation-demo"


def _default_home() -> Path:
    return Path(os.environ.get("USERPROFILE", Path.home())) / "ARGOS_MLOPS_LOCAL"


@dataclass(frozen=True)
class MlflowSettings:
    tracking_uri: str = DEFAULT_TRACKING_URI
    registry_uri: str = DEFAULT_TRACKING_URI
    mlops_home: Path = field(default_factory=_default_home)
    download_dir: Path = field(default_factory=lambda: _default_home() / "downloads")
    request_timeout_s: int = 10
    max_retries: int = 2
    backoff_factor: int = 1

    @classmethod
    def from_env(cls) -> MlflowSettings:
        env = os.environ
        tracking = env.get("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
        home = Path(env["ARGOS_MLOPS_HOME"]) if env.get("ARGOS_MLOPS_HOME") else _default_home()
        return cls(
            tracking_uri=tracking,
            registry_uri=env.get("MLFLOW_REGISTRY_URI", tracking),
            mlops_home=home,
            download_dir=Path(env.get("ARGOS_MLOPS_DOWNLOAD_DIR", home / "downloads")),
            request_timeout_s=int(env.get("MLFLOW_HTTP_REQUEST_TIMEOUT", 10)),
            max_retries=int(env.get("MLFLOW_HTTP_REQUEST_MAX_RETRIES", 2)),
            backoff_factor=int(env.get("MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR", 1)),
        )

    def apply_http_policy(self) -> None:
        """Make the MLflow client of THIS process use our timeout and retry policy."""
        os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = str(self.request_timeout_s)
        os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = str(self.max_retries)
        os.environ["MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR"] = str(self.backoff_factor)
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")


def utf8_console() -> None:
    """MLflow prints emoji (e.g. 'View run ...'); the Windows cp1252 console cannot."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
