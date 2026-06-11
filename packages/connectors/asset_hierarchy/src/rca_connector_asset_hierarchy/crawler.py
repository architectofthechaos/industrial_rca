"""Pure crawl logic over an injected httpx.AsyncClient (no server, no FastMCP).

AF paths are ``\\\\{Server}\\{Database}\\{Site}\\{Area}\\{Unit}\\{Asset}``; depth is
counted in segments below the database (Site=1 ... Asset=4) and elements deeper than
``max_depth`` are skipped. Elements templated Site/Area/Unit become hierarchy nodes;
everything else is an asset proposal whose unit/area/site are its path ancestors.
Ancestors resolve against hierarchy-templated elements only, so an asset nested under
another ASSET raises MalformedResponse instead of silently wiring the parent asset in
as its unit.
ISO 14224 classes come from ``rca_mar.pattern_rules.apply_rules`` (spec §2.3): the
template rule and the tag rule are both tried, the higher-confidence match wins, and
the method is the winning rule id (or "none" with class None / confidence 0.0).

``crawl_subtree`` lists strict descendants of one element; ancestors ABOVE the root
(needed for asset parent ids) are resolved by walking down from ``/assetdatabases``
with ``nameFilter`` — at most one call per ancestor level (≤3 extra calls).
"""
from __future__ import annotations

from typing import Any

import httpx
from rca_connector_sdk import MalformedResponse, NotFound
from rca_kg.slugs import slug
from rca_mar.pattern_rules import apply_rules

from .models import CrawlResult, DiscoveredAsset, DiscoveredHierarchyNode

_HIERARCHY_KINDS = {"Site": "site", "Area": "area", "Unit": "unit"}
_MAX_COUNT = 10_000


async def _get_json(client: httpx.AsyncClient, url: str,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await client.get(url, params=params)
    if resp.status_code == 404:
        raise NotFound(f"GET {url} -> 404")
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    return payload


def _depth_below_db(path: str) -> int:
    # "\\SERVER\DB\SITE\AREA" splits to ['', '', 'SERVER', 'DB', 'SITE', 'AREA']
    return len(path.split("\\")) - 4


def _classify(template_name: str | None, name: str) -> tuple[str | None, float, str]:
    """Spec §2.3: template rule, then tag rule on the element name; higher confidence wins."""
    by_template = apply_rules(template_name, "template") if template_name else None
    by_tag = apply_rules(name, "tag")
    best = by_template
    if by_tag is not None and (best is None or by_tag.confidence > best.confidence):
        best = by_tag
    if best is None:
        return None, 0.0, "none"
    return best.iso14224_class, best.confidence, best.rule_id


async def _project(client: httpx.AsyncClient, elements: list[dict[str, Any]], *,
                   plant_id: str, max_depth: int,
                   ancestor_webids: dict[str, str]) -> CrawlResult:
    """Shared projection: elements -> hierarchy nodes + asset proposals.

    ``ancestor_webids`` maps path -> WebId for elements NOT in the listing (the
    subtree-crawl ancestors); the full crawl passes an empty map. The ancestor
    lookup holds hierarchy-templated elements only (plus ``ancestor_webids``), so
    an asset whose parent is another asset fails the resolution loudly below.
    """
    in_scope = [el for el in elements if _depth_below_db(el["Path"]) <= max_depth]
    path_to_webid: dict[str, str] = dict(ancestor_webids)
    path_to_webid.update({el["Path"]: el["WebId"] for el in in_scope
                          if (el.get("TemplateName") or "") in _HIERARCHY_KINDS})

    hierarchy_nodes: list[DiscoveredHierarchyNode] = []
    asset_elements: list[dict[str, Any]] = []
    for el in in_scope:
        kind = _HIERARCHY_KINDS.get(el.get("TemplateName") or "")
        if kind is not None:
            parent_path = el["Path"].rsplit("\\", 1)[0]
            hierarchy_nodes.append(DiscoveredHierarchyNode(
                vendor_id=el["WebId"], vendor_path=el["Path"], kind=kind,  # type: ignore[arg-type]
                name=el["Name"], plant_id=plant_id,
                parent_vendor_id=path_to_webid.get(parent_path)))
        else:
            asset_elements.append(el)

    assets: list[DiscoveredAsset] = []
    for el in asset_elements:
        path, name = el["Path"], el["Name"]
        segments = path.split("\\")
        unit_path = "\\".join(segments[:-1])
        area_path = "\\".join(segments[:-2])
        site_path = "\\".join(segments[:-3])
        unit_name = segments[-2]
        try:
            unit_id = path_to_webid[unit_path]
            area_id = path_to_webid[area_path]
            site_id = path_to_webid[site_path]
        except KeyError as exc:
            raise MalformedResponse(
                f"asset {name!r} at {path!r}: unresolved ancestor path {exc}") from exc
        attrs = await _get_json(client, f"/elements/{el['WebId']}/attributes")
        iso_class, confidence, method = _classify(el.get("TemplateName"), name)
        assets.append(DiscoveredAsset(
            vendor_id=el["WebId"], vendor_path=path, plant_id=plant_id,
            unit_slug=slug(unit_name), name=name,
            proposed_canonical_id=f"asset:{plant_id}:{slug(unit_name)}:{slug(name)}",
            iso14224_class=iso_class, iso14224_class_confidence=confidence,
            iso14224_class_method=method,
            attributes={item["Name"]: str(item["Value"]) for item in attrs["Items"]},
            parent_unit_vendor_id=unit_id, parent_area_vendor_id=area_id,
            site_vendor_id=site_id))
    return CrawlResult(assets=assets, hierarchy_nodes=hierarchy_nodes)


async def crawl(client: httpx.AsyncClient, *, database_name: str, plant_id: str,
                max_depth: int = 6) -> CrawlResult:
    """Crawl a whole AF database (matched by Name; NotFound if absent)."""
    dbs = (await _get_json(client, "/assetdatabases"))["Items"]
    db = next((d for d in dbs if d["Name"] == database_name), None)
    if db is None:
        raise NotFound(f"AF database {database_name!r} not found")
    listing = await _get_json(
        client, f"/assetdatabases/{db['WebId']}/elements",
        params={"searchFullHierarchy": "true", "maxCount": _MAX_COUNT})
    return await _project(client, listing["Items"], plant_id=plant_id,
                          max_depth=max_depth, ancestor_webids={})


async def _resolve_ancestors(client: httpx.AsyncClient, root_path: str) -> dict[str, str]:
    """WebIds for every element ABOVE the subtree root: find the database whose Path
    prefixes the root's, then walk down one nameFilter call per ancestor segment."""
    dbs = (await _get_json(client, "/assetdatabases"))["Items"]
    db = next((d for d in dbs if root_path.startswith(d["Path"] + "\\")), None)
    if db is None:
        raise MalformedResponse(f"no asset database is a path prefix of {root_path!r}")
    segments = root_path[len(db["Path"]) + 1:].split("\\")
    ancestors: dict[str, str] = {}
    list_url = f"/assetdatabases/{db['WebId']}/elements"
    current_path = db["Path"]
    for segment in segments[:-1]:                      # everything above the root itself
        items = (await _get_json(client, list_url, params={"nameFilter": segment}))["Items"]
        current_path = f"{current_path}\\{segment}"
        match = next((it for it in items if it["Path"] == current_path), None)
        if match is None:
            raise MalformedResponse(f"ancestor element not found at {current_path!r}")
        ancestors[current_path] = match["WebId"]
        list_url = f"/elements/{match['WebId']}/elements"
    return ancestors


async def crawl_subtree(client: httpx.AsyncClient, *, root_web_id: str, plant_id: str,
                        max_depth: int = 6) -> CrawlResult:
    """Crawl one element's strict descendants. The root itself joins the result as a
    hierarchy node when templated Site/Area/Unit; either way its WebId (and those of
    its ancestors) resolves asset parent ids."""
    root = await _get_json(client, f"/elements/{root_web_id}")
    listing = await _get_json(
        client, f"/elements/{root_web_id}/elements",
        params={"searchFullHierarchy": "true", "maxCount": _MAX_COUNT})
    ancestors = await _resolve_ancestors(client, root["Path"])
    ancestors[root["Path"]] = root["WebId"]
    elements = list(listing["Items"])
    if (root.get("TemplateName") or "") in _HIERARCHY_KINDS:
        elements.append(root)
    return await _project(client, elements, plant_id=plant_id,
                          max_depth=max_depth, ancestor_webids=ancestors)


__all__ = ["crawl", "crawl_subtree"]
