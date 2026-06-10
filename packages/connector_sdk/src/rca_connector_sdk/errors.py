"""Exception taxonomy + mapping to the canonical ToolError (SPEC-002).

Connectors/SDK raise these internally; the orchestrator catches everything at the
boundary and returns a ToolError (tools never raise to the agent).
"""
from __future__ import annotations

import httpx
from rca_contracts import ToolError, ToolErrorCode


class ConnectorError(Exception):
    """Base for SDK/connector errors carrying a canonical code + retryable flag."""

    code: ToolErrorCode = "internal_error"
    retryable: bool = False


class SourceUnavailable(ConnectorError):
    code = "source_unavailable"
    retryable = True


class SourceTimeout(ConnectorError):
    code = "timeout"
    retryable = True


class UnresolvedSignal(ConnectorError):
    code = "unresolved_signal"
    retryable = False


class PermissionDenied(ConnectorError):
    code = "permission_denied"
    retryable = False


class NotFound(ConnectorError):
    code = "not_found"
    retryable = False


class UnitConversionAmbiguous(ConnectorError):
    code = "unit_conversion_ambiguous"
    retryable = False


class MalformedResponse(ConnectorError):
    """A source returned a response missing required fields / with unparseable data."""

    code = "validation_failed"
    retryable = False


def map_source_error(exc: Exception) -> ToolError:
    if isinstance(exc, ConnectorError):
        return ToolError(code=exc.code, message=str(exc) or exc.__class__.__name__,
                         retryable=exc.retryable)
    if isinstance(exc, httpx.TimeoutException):
        return ToolError(code="timeout", message=str(exc), retryable=True)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return ToolError(code="permission_denied", message=str(exc), retryable=False)
        if status == 404:
            return ToolError(code="not_found", message=str(exc), retryable=False)
        if status == 429:
            return ToolError(code="rate_limited", message=str(exc), retryable=True)
        retryable = status >= 500
        return ToolError(code="source_unavailable", message=str(exc), retryable=retryable)
    if isinstance(exc, httpx.HTTPError):       # ConnectError, TransportError, etc.
        return ToolError(code="source_unavailable", message=str(exc), retryable=True)
    return ToolError(code="internal_error", message=str(exc) or exc.__class__.__name__,
                     retryable=False)


__all__ = [
    "ConnectorError", "SourceUnavailable", "SourceTimeout", "UnresolvedSignal",
    "PermissionDenied", "NotFound", "UnitConversionAmbiguous", "MalformedResponse",
    "map_source_error",
]
