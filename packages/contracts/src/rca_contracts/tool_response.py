"""ToolResponse[T] — the uniform tool-return envelope.

Carries either a successful payload + Provenance, OR a ToolError — never both,
never neither. This makes "no data without provenance" (ADR-0010) and "return
errors, don't raise" (SPEC-002) structural rather than conventional.
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import model_validator

from ._base import StrictModel
from .provenance import Provenance
from .tool_error import ToolError

T = TypeVar("T")


class ToolResponse(StrictModel, Generic[T]):
    data: T | None = None
    provenance: Provenance | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> "ToolResponse[T]":
        success = self.data is not None and self.provenance is not None and self.error is None
        failure = self.error is not None and self.data is None and self.provenance is None
        if success == failure:
            raise ValueError(
                "ToolResponse must be exactly one of: success (data + provenance) "
                "or failure (error)."
            )
        return self

    @classmethod
    def ok(cls, data: T, provenance: Provenance) -> "ToolResponse[T]":
        return cls(data=data, provenance=provenance)

    @classmethod
    def fail(cls, error: ToolError) -> "ToolResponse[T]":
        return cls(error=error)
