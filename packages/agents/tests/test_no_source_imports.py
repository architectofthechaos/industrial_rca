"""§8 invariant: the agent source modules never import a connector/MAR/KG/simulator package.

Agents reach platform data ONLY through the ``ToolBox`` Protocol — in production via the
mounted entity MCP host (``McpToolBox`` over ``fastmcp.Client``), never by importing the
connector/MAR/KG/simulator code directly. This is enforced structurally here by walking the
AST of each source module and rejecting any forbidden top-level import.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "rca_agents"

# Modules that must stay free of source-layer imports (toolbox/mcp_toolbox + the three graphs
# + the leg base). Activities/workflow/worker/api may legitimately wire things up elsewhere.
GUARDED = [
    "gather_graph.py", "planning_graph.py", "rca_graph.py",
    "base.py", "toolbox.py", "mcp_toolbox.py",
]

FORBIDDEN_PREFIXES = ("rca_connector", "rca_mar", "rca_kg", "rca_simulator")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # node.module is None for relative `from . import x`; those are intra-package.
            if node.module:
                names.add(node.module)
    return names


def _is_forbidden(module: str) -> bool:
    root = module.split(".")[0]
    return any(root == p or root.startswith(p) for p in FORBIDDEN_PREFIXES)


def test_guarded_files_exist():
    missing = [f for f in GUARDED if not (SRC / f).exists()]
    assert not missing, f"guarded source files missing: {missing}"


def test_no_source_layer_imports_in_agent_modules():
    offenders: dict[str, list[str]] = {}
    for fname in GUARDED:
        path = SRC / fname
        bad = sorted(m for m in _imported_modules(path) if _is_forbidden(m))
        if bad:
            offenders[fname] = bad
    assert not offenders, (
        "§8 invariant violated — agent modules import connector/MAR/KG/simulator code: "
        f"{offenders}"
    )
