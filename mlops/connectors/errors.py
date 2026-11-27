"""Explicit errors of the ARGOS MLflow connector.

A future FastAPI layer maps them to HTTP codes: ``ServerUnavailableError`` -> 503,
``*NotFoundError`` -> 404, ``ForbiddenOperationError`` -> 403,
``ArtifactDownloadError`` -> 502.
"""

from __future__ import annotations


class MlflowConnectorError(Exception):
    """Base class of every connector error."""


class ServerUnavailableError(MlflowConnectorError):
    """The tracking or registry server cannot be reached (down, timeout, refused)."""


class NotFoundError(MlflowConnectorError):
    """Base class of the 'unknown resource' errors."""


class ExperimentNotFoundError(NotFoundError):
    pass


class RunNotFoundError(NotFoundError):
    pass


class RegisteredModelNotFoundError(NotFoundError):
    pass


class ModelVersionNotFoundError(NotFoundError):
    pass


class AliasNotFoundError(NotFoundError):
    pass


class ArtifactDownloadError(MlflowConnectorError):
    """An artifact could not be listed or downloaded (or the destination is not allowed)."""


class ForbiddenOperationError(MlflowConnectorError):
    """A write operation outside the demonstration scope was refused."""
