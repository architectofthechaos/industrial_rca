"""ToolError — tools return this rather than raising (SPEC-002)."""
from __future__ import annotations

from typing import Literal

from ._base import StrictModel

ToolErrorCode = Literal[
    "not_found",
    "ambiguous_input",
    "unresolved_signal",
    "unit_conversion_ambiguous",
    "source_unavailable",
    "rate_limited",
    "budget_exceeded",
    "permission_denied",
    "validation_failed",
    "timeout",
    "internal_error",
]


class ToolError(StrictModel):
    code: ToolErrorCode
    message: str
    retryable: bool
    details: dict | None = None
