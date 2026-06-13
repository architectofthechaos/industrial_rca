"""McpDocSource — DocSource adapter over the document entity MCP (Sprint 6 WI4 / D16 / G29).

Implements ``DocumentEmbeddingPipeline``'s ``DocSource`` Protocol
(``list_by_type``/``get``) by driving an *open* fastmcp ``Client`` against the mounted
``document.list_by_type`` / ``document.get`` tools, then mapping each ``DocumentRef`` to the
plain dict shape the pipeline reads (``document_id``/``title``/``doc_type``/``excerpt``).

The envelope handling (``_call``/``_require_ok``) mirrors ``McpToolBox`` exactly: a JSON-mode
``ToolResponse`` is validated non-strictly (ISO datetimes / string UUIDs coerce back) and the
exactly-one-of invariant still runs; an error envelope raises. Imports ONLY ``rca_contracts``
— never a connector/MAR/KG module (§8 invariant).
"""
from __future__ import annotations

from typing import Any

from rca_contracts import ToolResponse


def _ref_to_dict(ref: dict) -> dict:
    """Map a DocumentRef-shaped dict to the pipeline's read shape.

    The pipeline reads ``title`` and ``excerpt`` (and ``document_id`` from list rows). A null
    DocumentRef.excerpt (empty source content) is normalised to "" so the pipeline's
    ``title\\nexcerpt`` body join never concatenates ``None``.
    """
    return {
        "document_id": ref.get("document_id"),
        "title": ref.get("title", ""),
        "doc_type": ref.get("doc_type"),
        "excerpt": ref.get("excerpt") or "",
    }


class McpDocSource:
    """Production DocSource over the mounted document entity MCP (in-process or HTTP client)."""

    def __init__(self, client: Any) -> None:
        self._c = client            # an *open* fastmcp.Client

    async def _call(self, tool: str, request: dict) -> ToolResponse[Any]:
        res = await self._c.call_tool(tool, {"request": request})
        payload = res.structured_content
        if payload is None:
            raise RuntimeError(f"{tool} returned no structured content: {res.data!r}")
        return ToolResponse[Any].model_validate(payload, strict=False)

    @staticmethod
    def _require_ok(resp: ToolResponse[Any], tool: str) -> ToolResponse[Any]:
        if resp.error is not None:
            raise RuntimeError(f"{tool} failed: {resp.error}")
        return resp

    # Embed the WHOLE corpus per type: document.list_by_type defaults top=20, which would
    # silently cap enumeration (and the embedding set) on a plant with >20 docs of a type.
    _LIST_TOP = 10_000

    async def list_by_type(self, doc_type: str, plant_id: str) -> list[dict]:
        resp = await self._call(
            "document.list_by_type",
            {"doc_type": doc_type, "plant_id": plant_id, "top": self._LIST_TOP})
        self._require_ok(resp, "document.list_by_type")
        return [_ref_to_dict(dict(r)) for r in (resp.data or [])]

    async def get(self, document_id: str, plant_id: str) -> dict:
        resp = await self._call("document.get",
                                {"document_id": document_id, "plant_id": plant_id})
        self._require_ok(resp, "document.get")
        return _ref_to_dict(dict(resp.data or {}))


__all__ = ["McpDocSource"]
