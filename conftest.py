"""Test isolation: ignore the developer's environment variables (and .env).

Without this, a personal setting such as SOURCE=webcam would change the test results.
"""

import pytest

from visionhub.config import Settings


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
