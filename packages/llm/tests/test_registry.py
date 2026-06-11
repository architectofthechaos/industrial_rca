"""Prompt registry: frontmatter parsing, variable validation, output_schema validation,
rendering, and loading the packaged prompt set."""
from __future__ import annotations

import pytest

from rca_llm.registry import (
    PromptValidationError,
    default_registry,
    parse_prompt,
)

_GOOD = """---
name: t
version: v1
model: claude-opus-4-8
temperature: 0.0
max_tokens: 100
variables: [a, b]
output_schema:
  type: object
  properties:
    x: {type: string}
---
Hello {{ a }} and {{ b }}.
"""


def test_parse_and_render_roundtrip():
    p = parse_prompt(_GOOD)
    assert p.name == "t" and p.version == "v1"
    assert p.render({"a": "1", "b": "2"}).strip() == "Hello 1 and 2."


def test_missing_frontmatter_rejected():
    with pytest.raises(PromptValidationError):
        parse_prompt("no frontmatter here {{ a }}")


def test_undeclared_variable_in_body_rejected():
    bad = _GOOD.replace("variables: [a, b]", "variables: [a]")
    with pytest.raises(PromptValidationError):
        parse_prompt(bad)


def test_declared_but_unused_variable_rejected():
    bad = _GOOD.replace("variables: [a, b]", "variables: [a, b, c]")
    with pytest.raises(PromptValidationError):
        parse_prompt(bad)


def test_invalid_output_schema_rejected():
    bad = _GOOD.replace("type: object", "type: not_a_real_type")
    with pytest.raises(PromptValidationError):
        parse_prompt(bad)


def test_render_missing_variable_raises():
    p = parse_prompt(_GOOD)
    with pytest.raises(PromptValidationError):
        p.render({"a": "1"})


def test_default_registry_loads_all_packaged_prompts():
    reg = default_registry()
    names = {n for (n, _v) in reg.names()}
    # the planning + gather + rca prompt families must all load and validate
    assert {"parse_probe_intent", "build_failure_mode_shortlist", "draft_evidence_plan",
            "rca_build_fishbone", "rca_run_five_whys_step", "rca_rank_hypotheses",
            "detect_tag_anomalies"} <= names
    # every packaged prompt validated cleanly (no exception raised above)
    assert reg.get_prompt("parse_probe_intent", "v1").model.startswith("claude-")
