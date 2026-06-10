"""Sprint 1 WI3 — PI AF element index for the asset-hierarchy endpoints.

Walks the fixture plant tree (Site -> Area -> Unit -> Asset) once at app
construction and builds an immutable in-memory index of AF elements. Routes in
``app.py`` only look up and serialize; all tree/filter logic lives here.

AF paths are *synthesized* with real PI AF semantics
(``\\\\{AFServer}\\{Database}\\{Element}\\...``), e.g.
``\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO\\AREA-100\\UNIT-101\\P-101A``.
NOTE: asset fixtures carry a legacy ``external_ids.pi_af_path``
(``\\\\PI-DEMO\\Refinery\\P-101A``) that does NOT match these element paths —
reconciling the two is a known Sprint-2 connector concern; fixtures stay as-is.

WebIDs reuse the deterministic stream scheme (``webid.encode_webid`` over the
AF path), so the same path always yields the same WebID across restarts.
Stream WebIDs encode ``tag.role`` keys (e.g. ``P-101A.discharge_pressure``)
while element WebIDs encode ``\\\\{Server}\\...`` paths, so the two
namespaces cannot collide even though they share the same codec.

Template/category mapping (synthesized from tree level): site -> ``Site``,
area -> ``Area``, unit -> ``Unit``; assets use the fixture's ``template_class``
as TemplateName with CategoryNames ``["Asset"]``.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Iterable, Iterator

from ..fixtures.schema import Asset, RefPlant
from .webid import encode_webid

AF_SERVER = "PI-DEMO"
DEFAULT_AF_DATABASE = "Refinery-GC"
DEFAULT_MAX_COUNT = 1000          # PI Web API's default maxCount


@dataclass(frozen=True)
class AfElement:
    web_id: str
    name: str
    description: str
    path: str
    template_name: str
    category_names: tuple[str, ...]
    children: tuple["AfElement", ...] = ()
    attributes: tuple[tuple[str, object], ...] = ()   # (Name, Value) pairs

    @property
    def has_children(self) -> bool:
        return bool(self.children)

    def as_item(self) -> dict:
        return {
            "WebId": self.web_id,
            "Name": self.name,
            "Description": self.description,
            "Path": self.path,
            "TemplateName": self.template_name,
            "CategoryNames": list(self.category_names),
            "HasChildren": self.has_children,
        }


@dataclass(frozen=True)
class AfDatabase:
    web_id: str
    name: str
    description: str
    path: str
    roots: tuple[AfElement, ...] = ()

    def as_item(self) -> dict:
        return {"WebId": self.web_id, "Name": self.name,
                "Description": self.description, "Path": self.path}


def _asset_attributes(asset: Asset) -> tuple[tuple[str, object], ...]:
    # Flat Name/Value list, restricted to fields the asset fixture schema has
    # (no ISO14224Level / LocationDescription in the fixture -> not exposed).
    return (
        ("Manufacturer", asset.nameplate.manufacturer),
        ("Model", asset.nameplate.model),
        ("SerialNumber", asset.nameplate.serial),
        ("Criticality", asset.criticality),
        ("ISO14224Class", asset.iso14224_class),
        ("ServiceDescription", asset.service),
    )


def _element(name: str, description: str, parent_path: str, level: str,
             *, template: str | None = None,
             children: tuple[AfElement, ...] = (),
             attributes: tuple[tuple[str, object], ...] = ()) -> AfElement:
    path = f"{parent_path}\\{name}"
    return AfElement(
        web_id=encode_webid(path), name=name, description=description,
        path=path, template_name=template or level, category_names=(level,),
        children=children, attributes=attributes,
    )


class AfIndex:
    """Immutable AF view of one fixture plant: a single database + element tree."""

    def __init__(self, rp: RefPlant, *, database: str = DEFAULT_AF_DATABASE):
        site = rp.plant.site
        db_path = f"\\\\{AF_SERVER}\\{database}"

        site_path = f"{db_path}\\{site.site_id}"
        areas = []
        for area in site.areas:
            area_path = f"{site_path}\\{area.area_id}"
            units = []
            for unit in area.units:
                assets = tuple(
                    _element(a.tag, a.service, f"{area_path}\\{unit.unit_id}",
                             "Asset", template=a.template_class,
                             attributes=_asset_attributes(a))
                    for a in (rp.assets[ref.asset_ref] for ref in unit.equipment)
                )
                units.append(_element(unit.unit_id, unit.name, area_path,
                                      "Unit", children=assets))
            areas.append(_element(area.area_id, area.name, site_path, "Area",
                                  children=tuple(units)))

        root = _element(site.site_id, site.name, db_path, "Site",
                        children=tuple(areas))
        self.database = AfDatabase(
            web_id=encode_webid(db_path), name=database,
            description=f"AF database for {site.name}", path=db_path,
            roots=(root,),
        )
        self._by_web_id: dict[str, AfElement] = {
            el.web_id: el
            for r in self.database.roots for el in _self_and_descendants(r)
        }

    def element(self, web_id: str) -> AfElement | None:
        return self._by_web_id.get(web_id)


def _self_and_descendants(el: AfElement) -> Iterator[AfElement]:
    yield el
    for child in el.children:
        yield from _self_and_descendants(child)


def select(children: Iterable[AfElement], *,
           name_filter: str | None = None,
           search_full_hierarchy: bool = False,
           max_count: int = DEFAULT_MAX_COUNT) -> list[AfElement]:
    """PI element-list semantics shared by both ``.../elements`` routes.

    ``children`` is the direct child list (an element's children, or the
    database's root elements). ``search_full_hierarchy`` flattens each child's
    whole subtree (so a database query includes its roots; an element query
    returns strict descendants). ``name_filter`` is a case-insensitive ``*``/
    ``?`` glob; ``max_count`` truncates after filtering, as PI does.
    """
    if search_full_hierarchy:
        pool = [el for c in children for el in _self_and_descendants(c)]
    else:
        pool = list(children)
    if name_filter:
        pattern = name_filter.lower()
        pool = [el for el in pool if fnmatchcase(el.name.lower(), pattern)]
    # max(0, ...) clamps negative maxCount to empty; real PI Web API returns HTTP 400
    # for negative maxCount — accepted Sprint-1 deviation.
    return pool[:max(0, max_count)]


__all__ = ["AF_SERVER", "DEFAULT_AF_DATABASE", "DEFAULT_MAX_COUNT",
           "AfDatabase", "AfElement", "AfIndex", "select"]
