"""S2.4 — seed SAP PM notifications from the scenario fixtures.

Only a SUBSET of the plant runs on SAP PM (``SAP_ASSETS``), and some of those
assets also appear in Maximo — so the same underlying event shows up under SAP's
different field names/codes (QMNUM/EQUNR/QMTXT/QMART/PRIOK/FECOD), exercising the
connector's cross-source dedup + normalization. Timestamps use SAP yyyymmdd.
"""
from __future__ import annotations

from ..fixtures.schema import RefPlant
from ..fixtures.scenario_expander import events_by_sink

# subset of plant on SAP PM; P-101A overlaps Maximo, P-101B does NOT use SAP
SAP_ASSETS = {"P-101A", "P-103A"}

# Maximo priority -> SAP PRIOK coding scheme (deliberately different values)
_PRIOK = {1: "1", 2: "2", 3: "3"}
# Maximo problem code -> SAP failure code (FECOD) scheme (different coding)
_FECOD = {"LEAK": "0010", "VIBR": "0020", "ELEC": "0030", "CAVN": "0040"}


def _sap_equipment(rp: RefPlant, asset_tag: str) -> str:
    asset = rp.assets.get(asset_tag)
    if asset is None:
        return asset_tag
    return str(asset.external_ids.get("sap_equipment", asset_tag))


def _qmnum(wo_number: str) -> str:
    # SAP notification number: digits only, distinct from the Maximo wonum string
    digits = "".join(ch for ch in wo_number if ch.isdigit())
    return digits.zfill(8)[-8:] if digits else wo_number


def seed_notifications(rp: RefPlant) -> list[dict]:
    out: list[dict] = []
    for sid, sc in rp.scenarios.items():
        if sc.affected_asset not in SAP_ASSETS:
            continue
        for ts, ev in events_by_sink(rp, sid).get("maximo", []):
            p = ev.payload
            out.append({
                "QMNUM": _qmnum(p["wo_number"]),
                "EQUNR": _sap_equipment(rp, sc.affected_asset),
                "QMTXT": p.get("narrative", ""),
                "QMART": "M2",                                  # maintenance notification
                "PRIOK": _PRIOK.get(p.get("priority"), "4"),
                "FECOD": _FECOD.get(p.get("problem_code"), ""),
                "AUSVN": ts.strftime("%Y%m%d"),                # SAP date yyyymmdd
            })
    return out


__all__ = ["SAP_ASSETS", "seed_notifications"]
