"""Configuration: global settings from environment variables (or a .env file),
and per-use-case settings from ``usecases/<use_case>/config.yaml``.

Every variable is documented in ``.env.example``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from visionhub.contracts import Thresholds, UseCase

USECASES_DIR = Path(__file__).resolve().parent.parent / "usecases"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    device: Literal["cpu", "cuda"] = "cpu"

    source: Literal["synthetic", "folder", "video", "webcam"] = "synthetic"
    source_path: str = ""
    webcam_index: int = 0
    synthetic_seed: int = 0

    roi: str = ""  # "x,y,w,h" in pixels, empty = full image
    anonymize: bool = False

    pipeline_enabled: bool = True
    pipeline_fps: float = Field(default=2.0, gt=0)

    # NoDecode: read "quality,safety" as a plain string, split by the validator below.
    enabled_use_cases: Annotated[list[UseCase], NoDecode] = Field(
        default_factory=lambda: list(UseCase)
    )
    workstation_id: str = "WS-01"
    camera_id: str = "CAM-01"

    db_path: str = "var/events.db"  # ":memory:" for no file at all

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    dashboard_port: int = 8501
    api_url: str = "http://localhost:8000"

    @field_validator("enabled_use_cases", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("roi")
    @classmethod
    def _check_roi(cls, value: str) -> str:
        if value.strip() and len(value.split(",")) != 4:
            raise ValueError("ROI must be 'x,y,w,h' (4 integers) or empty")
        return value

    def roi_box(self) -> tuple[int, int, int, int] | None:
        if not self.roi.strip():
            return None
        x, y, w, h = (int(v) for v in self.roi.split(","))
        return x, y, w, h


class UseCaseConfig(BaseModel):
    """Content of ``usecases/<use_case>/config.yaml``."""

    analyzer_class: str  # "package.module:ClassName"
    thresholds: Thresholds
    params: dict[str, Any] = Field(default_factory=dict)


def load_use_case_config(use_case: UseCase, base_dir: Path = USECASES_DIR) -> UseCaseConfig:
    path = base_dir / use_case.value / "config.yaml"
    with path.open(encoding="utf-8") as f:
        return UseCaseConfig.model_validate(yaml.safe_load(f))
