"""Acceptance gate: no vendor-prefixed MCP tool names, no SignalID, anywhere in src.

Sprint 2b restructured the data-access surface into one MCP server per canonical entity
(spec §7.1) with tool names in entity vocabulary, never vendor vocabulary (§7.2, the hard
rule). This hermetic test (no sims, no DB) enforces that acceptance criterion by walking the
source trees and asserting:

  1. ZERO registered tool-name string literals with a vendor prefix
     (`pi.`, `maximo.`, `documents.`, `assets.`). These were replaced by `tag.` /
     `operator_log.` / `work_order.` / `document.` / `asset.` respectively.
  2. ZERO occurrences of `SignalID` / `SignalDescriptor` (2b acceptance #11 — replaced by
     canonical_id + TagDescriptor in the entity-vocabulary contracts).

Scope: `packages/*/src` and `packages/connectors/*/src`. Excludes:
  - `packages/connectors/sap_pm/` — parked for Phase 1 (Maximo is the sole CMMS source);
    it intentionally keeps `sap_pm.*` and is not in the entity surface, only `parity:cross`.
  - any path containing `/tests/` — test fixtures may reference old names in prose/asserts.
"""
import pathlib
import re

# Registered tool names like name="pi.get_series" / tool="maximo.foo" / "documents.bar" /
# "assets.baz". The legacy vendor prefixes that the entity rename eliminated.
PATTERN = re.compile(r'"(pi|maximo|documents|assets)\.[a-z_]+"')

# A SQLAlchemy column reference `ForeignKey("assets.asset_id")` is `<table>.<column>`, NOT an
# MCP tool name — the MAR `assets` DB table legitimately exists. No tool name is ever written
# inside ForeignKey(...), so skipping that exact context cannot mask a real tool-name leak.
_FOREIGN_KEY = re.compile(r"ForeignKey\(")

SIGNAL_PATTERN = re.compile(r"\b(SignalID|SignalDescriptor)\b")

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _src_files() -> list[pathlib.Path]:
    """All .py files under packages/*/src and packages/connectors/*/src, minus exclusions."""
    packages = _REPO_ROOT / "packages"
    files: list[pathlib.Path] = []
    files += packages.glob("*/src/**/*.py")
    files += (packages / "connectors").glob("*/src/**/*.py")
    return [
        p for p in sorted(set(files))
        if "/tests/" not in p.as_posix()
        and "/connectors/sap_pm/" not in p.as_posix()
    ]


def test_no_vendor_prefixed_tool_names_in_src():
    hits: list[str] = []
    for path in _src_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if _FOREIGN_KEY.search(line):
                continue  # SQLAlchemy table.column reference, not a tool name
            for match in PATTERN.finditer(line):
                rel = path.relative_to(_REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {match.group(0)}  ->  {line.strip()}")
    assert not hits, (
        "vendor-prefixed MCP tool names must not appear in src (use entity vocabulary: "
        "tag./operator_log./work_order./document./asset.):\n" + "\n".join(hits)
    )


def test_no_signal_id_or_descriptor_in_src():
    hits: list[str] = []
    for path in _src_files():
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for match in SIGNAL_PATTERN.finditer(line):
                rel = path.relative_to(_REPO_ROOT)
                hits.append(f"{rel}:{lineno}: {match.group(0)}  ->  {line.strip()}")
    assert not hits, (
        "SignalID/SignalDescriptor were removed in 2b (acceptance #11); use canonical_id + "
        "TagDescriptor:\n" + "\n".join(hits)
    )
