"""Hermetic PI AF fake for crawler tests — mirrors the real simulator field-for-field.

Same routes, JSON casing and semantics as ``rca_simulator/rca_simulator/pi/app.py``
(verified against ``rca_simulator/tests/test_pi_af_hierarchy.py``): ``{"Items": [...]}``
envelopes on list routes, a bare object for single-element GETs, 404 on unknown WebIds,
``nameFilter`` as a case-insensitive ``*``/``?`` glob, ``searchFullHierarchy`` flattening
each child's whole subtree, ``maxCount`` truncating after filtering (negatives clamp to
empty). WebIds replicate the sim's deterministic scheme — ``"S1" + urlsafe_b64(path)``
without padding — computed locally so the sim never enters this venv (ADR-0012).

The tree mirrors refplant: DB "Refinery-GC" -> SITE-DEMO -> AREA-100 -> UNIT-101
(P-101A, P-101B) / UNIT-102 (P-102A) and AREA-200 -> UNIT-201 (P-103A).
``include_mystery=True`` adds MYSTERY-1 (template ``mystery_thing``) under UNIT-102
for the unknown-class test; count-sensitive tests leave the flag off.
"""
from __future__ import annotations

import base64
from fnmatch import fnmatchcase
from typing import Any, Iterator

import httpx
from fastapi import FastAPI, HTTPException

AF_SERVER = "PI-DEMO"
DB_NAME = "Refinery-GC"
DB_PATH = f"\\\\{AF_SERVER}\\{DB_NAME}"
DEFAULT_MAX_COUNT = 1000  # PI Web API's default maxCount


def webid(path: str) -> str:
    """The sim's deterministic WebId scheme, replicated locally."""
    return "S1" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def _asset_attrs(manufacturer: str, model: str, serial: str, criticality: str,
                 iso_class: str, service: str) -> list[tuple[str, Any]]:
    return [("Manufacturer", manufacturer), ("Model", model), ("SerialNumber", serial),
            ("Criticality", criticality), ("ISO14224Class", iso_class),
            ("ServiceDescription", service)]


def _hierarchy(include_mystery: bool) -> dict[str, Any]:
    """Refplant mirror as a plain dict: {name, template, description, children, attributes}."""
    unit_102_children = [
        {"name": "P-102A", "template": "centrifugal_pump", "description": "injection pump",
         "attributes": _asset_attrs("Sulzer", "HPX-3100", "SN-2019-00310", "medium",
                                    "pump.centrifugal", "injection pump")},
    ]
    if include_mystery:
        unit_102_children.append(
            {"name": "MYSTERY-1", "template": "mystery_thing", "description": "unidentified skid",
             "attributes": [("Manufacturer", "Acme"), ("ServiceDescription", "unidentified skid")]})
    return {
        "name": "SITE-DEMO", "template": "Site", "description": "Demo Refinery",
        "children": [
            {"name": "AREA-100", "template": "Area", "description": "Crude Unit", "children": [
                {"name": "UNIT-101", "template": "Unit", "description": "Crude Distillation",
                 "children": [
                     {"name": "P-101A", "template": "centrifugal_pump",
                      "description": "charge pump",
                      "attributes": _asset_attrs("Sulzer", "AHLSTAR-A22-50", "SN-2018-00471",
                                                 "high", "pump.centrifugal", "charge pump")},
                     {"name": "P-101B", "template": "centrifugal_pump",
                      "description": "boiler feed water pump",
                      "attributes": _asset_attrs("Sulzer", "AHLSTAR-A22-50", "SN-2018-00472",
                                                 "high", "pump.centrifugal",
                                                 "boiler feed water pump")},
                 ]},
                {"name": "UNIT-102", "template": "Unit", "description": "Hydrotreater Feed",
                 "children": unit_102_children},
            ]},
            {"name": "AREA-200", "template": "Area", "description": "Tank Farm", "children": [
                {"name": "UNIT-201", "template": "Unit", "description": "Transfer", "children": [
                    {"name": "P-103A", "template": "centrifugal_pump",
                     "description": "transfer pump",
                     "attributes": _asset_attrs("Sulzer", "OH2-200", "SN-2017-00188", "low",
                                                "pump.centrifugal", "transfer pump")},
                ]},
            ]},
        ],
    }


class _Element:
    def __init__(self, node: dict[str, Any], parent_path: str):
        self.path = f"{parent_path}\\{node['name']}"
        self.web_id = webid(self.path)
        self.name: str = node["name"]
        self.description: str = node.get("description", "")
        self.template: str = node["template"]
        self.attributes: list[tuple[str, Any]] = node.get("attributes", [])
        self.children: list[_Element] = [_Element(c, self.path)
                                         for c in node.get("children", [])]

    def as_item(self) -> dict[str, Any]:
        category = self.template if self.template in {"Site", "Area", "Unit"} else "Asset"
        return {"WebId": self.web_id, "Name": self.name, "Description": self.description,
                "Path": self.path, "TemplateName": self.template,
                "CategoryNames": [category], "HasChildren": bool(self.children)}


def _self_and_descendants(el: _Element) -> Iterator[_Element]:
    yield el
    for child in el.children:
        yield from _self_and_descendants(child)


def _select(children: list[_Element], *, name_filter: str | None,
            search_full_hierarchy: bool, max_count: int) -> list[_Element]:
    pool = ([el for c in children for el in _self_and_descendants(c)]
            if search_full_hierarchy else list(children))
    if name_filter:
        pattern = name_filter.lower()
        pool = [el for el in pool if fnmatchcase(el.name.lower(), pattern)]
    return pool[:max(0, max_count)]


def make_fake_af_app(include_mystery: bool = False) -> FastAPI:
    app = FastAPI(title="Fake PI AF")
    root = _Element(_hierarchy(include_mystery), DB_PATH)
    db_web_id = webid(DB_PATH)
    by_web_id = {el.web_id: el for el in _self_and_descendants(root)}

    def resolve(web_id: str) -> _Element:
        el = by_web_id.get(web_id)
        if el is None:
            raise HTTPException(status_code=404, detail="Element not found")
        return el

    @app.get("/assetdatabases")
    def assetdatabases() -> dict[str, Any]:
        return {"Items": [{"WebId": db_web_id, "Name": DB_NAME,
                           "Description": "AF database for Demo Refinery", "Path": DB_PATH}]}

    @app.get("/assetdatabases/{web_id}/elements")
    def database_elements(web_id: str, nameFilter: str | None = None,
                          searchFullHierarchy: bool = False,
                          maxCount: int = DEFAULT_MAX_COUNT) -> dict[str, Any]:
        if web_id != db_web_id:
            raise HTTPException(status_code=404, detail="Asset database not found")
        els = _select([root], name_filter=nameFilter,
                      search_full_hierarchy=searchFullHierarchy, max_count=maxCount)
        return {"Items": [el.as_item() for el in els]}

    @app.get("/elements/{web_id}")
    def element(web_id: str) -> dict[str, Any]:
        return resolve(web_id).as_item()

    @app.get("/elements/{web_id}/elements")
    def element_children(web_id: str, nameFilter: str | None = None,
                         searchFullHierarchy: bool = False,
                         maxCount: int = DEFAULT_MAX_COUNT) -> dict[str, Any]:
        el = resolve(web_id)
        els = _select(el.children, name_filter=nameFilter,
                      search_full_hierarchy=searchFullHierarchy, max_count=maxCount)
        return {"Items": [e.as_item() for e in els]}

    @app.get("/elements/{web_id}/attributes")
    def element_attributes(web_id: str) -> dict[str, Any]:
        el = resolve(web_id)
        return {"Items": [{"WebId": webid(f"{el.path}|{name}"), "Name": name, "Value": value}
                          for name, value in el.attributes]}

    return app


def fake_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake-af")


__all__ = ["AF_SERVER", "DB_NAME", "DB_PATH", "fake_client", "make_fake_af_app", "webid"]
