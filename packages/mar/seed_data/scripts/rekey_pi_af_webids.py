"""One-time re-key of the register's `pi_af` aliases from legacy AF paths to AF WebIds.

Rewrites each asset's `external_ids.pi_af` value in the seed register to the mapping
form ``{external_id: <WebId>, vendor_path: <AF Path>}`` that seed_from_register accepts
(WebIds are stable across AF path renames — Sprint 2a decision; the path is kept as
display/debug provenance in `vendor_path`).

Online mode (the default) is AUTHORITATIVE: it crawls the live PI AF simulator with the
asset_hierarchy connector and matches discovered assets to register entries by tag
(AF element Name == register tag). ``--offline`` exists only for when the sim is down:
it mirrors the sim's documented deterministic WebId scheme —
``"S1" + base64.urlsafe_b64encode(path).rstrip("=")`` — over the hardcoded refplant
paths, which yields byte-identical output to online mode by construction.

The YAML round-trip preserves the file's leading ``#`` comment block and dumps with
``sort_keys=False``, so key order survives and re-running the script is idempotent.

Usage:
    uv run python packages/mar/seed_data/scripts/rekey_pi_af_webids.py [--offline]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from pathlib import Path

import httpx
import yaml

from rca_connector_asset_hierarchy.crawler import crawl

DEFAULT_REGISTER = Path(__file__).resolve().parents[1] / "refplant_assets.yaml"

# Offline fallback: the two refplant register assets' AF paths (online mode discovers
# these same paths from the sim; mismatch would mean the sim hierarchy drifted).
OFFLINE_PATHS = {
    "P-101A": "\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO\\AREA-100\\UNIT-101\\P-101A",
    "P-103A": "\\\\PI-DEMO\\Refinery-GC\\SITE-DEMO\\AREA-200\\UNIT-201\\P-103A",
}


def _webid(path: str) -> str:
    """The simulator's documented deterministic WebId scheme, replicated locally."""
    return "S1" + base64.urlsafe_b64encode(path.encode()).decode().rstrip("=")


def _leading_comment_block(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line + "\n")
    return "".join(lines)


async def _discover_online(base_url: str, database: str,
                           plant_id: str) -> dict[str, tuple[str, str]]:
    """tag -> (WebId, AF path) discovered by crawling the live AF simulator."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        result = await crawl(client, database_name=database, plant_id=plant_id)
    return {a.name: (a.vendor_id, a.vendor_path) for a in result.assets}


def _rekey(register_path: Path, by_tag: dict[str, tuple[str, str]]) -> None:
    text = register_path.read_text()
    comment = _leading_comment_block(text)
    doc = yaml.safe_load(text)
    for asset in doc.get("assets", []):
        tag = str(asset["tag"])
        if "pi_af" not in (asset.get("external_ids") or {}):
            continue
        if tag not in by_tag:
            raise SystemExit(
                f"register entry {tag!r} has a pi_af alias but no AF element named {tag!r} "
                f"was discovered; refusing a partial re-key")
        web_id, vendor_path = by_tag[tag]
        asset["external_ids"]["pi_af"] = {"external_id": web_id, "vendor_path": vendor_path}
    register_path.write_text(comment + yaml.safe_dump(doc, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--database", default="Refinery-GC")
    parser.add_argument("--plant-id", default="refinery-gc")
    parser.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    parser.add_argument("--offline", action="store_true",
                        help="compute WebIds from the hardcoded refplant paths instead of "
                             "crawling (online mode is authoritative)")
    args = parser.parse_args()

    if args.offline:
        by_tag = {tag: (_webid(path), path) for tag, path in OFFLINE_PATHS.items()}
    else:
        by_tag = asyncio.run(_discover_online(args.base_url, args.database, args.plant_id))
    _rekey(args.register, by_tag)
    print(f"re-keyed pi_af aliases in {args.register}")


if __name__ == "__main__":
    main()
