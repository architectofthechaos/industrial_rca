"""DocumentRef — a canonical reference to a source document (SPEC-001)."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from ._base import StrictModel
from ._ids import AssetID

DocType = Literal["datasheet", "p_and_id", "rca_report", "soop", "manual", "other"]


class DocumentRef(StrictModel):
    document_id: str
    asset_id: AssetID | None = None
    title: str
    doc_type: DocType
    uri: str
    last_modified: AwareDatetime
    excerpt: str | None = None                 # relevant snippet / fetched content for the probe
