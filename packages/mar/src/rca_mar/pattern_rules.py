"""Deterministic pattern-rule registry (Sprint 2a §1.5).

The single source of truth for tag/template heuristics. Rules ship as a
versioned registry (seed_data/pattern_rules.yaml, overridable via
MAR_PATTERN_RULES_PATH) and are consumed by the AF crawler (class assignment)
and the MAR resolution layer (step-3 rule matching). Provenance is written as
the matching rule's id (e.g. 'rule:pump_p_tag').

Matching uses regex.search — rule authors are responsible for anchors (the
shipped rules are anchored). The highest-confidence matching rule wins; ties
break on file order.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

APPLIES_TO = frozenset({"tag", "template", "name", "path"})
_DEFAULT_PATH = Path(__file__).parents[2] / "seed_data" / "pattern_rules.yaml"
_ENV_PATH = "MAR_PATTERN_RULES_PATH"


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    # PatternRule is frozen, so the compiled regex lives in this module-level cache
    # instead of an instance attribute.
    return re.compile(pattern)


@dataclass(frozen=True)
class PatternRule:
    """One deterministic heuristic: regex -> ISO 14224 class at a fixed confidence."""

    id: str
    pattern: str
    iso14224_class: str
    confidence: float
    applies_to: str

    def __post_init__(self) -> None:
        if self.applies_to not in APPLIES_TO:
            raise ValueError(f"rule {self.id!r}: applies_to {self.applies_to!r}"
                             f" not in {sorted(APPLIES_TO)}")
        if not 0 < self.confidence <= 1:
            raise ValueError(f"rule {self.id!r}: confidence {self.confidence} not in (0, 1]")
        try:
            _compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"rule {self.id!r}: invalid pattern {self.pattern!r}: {exc}") from exc

    @property
    def regex(self) -> re.Pattern[str]:
        return _compile(self.pattern)


@dataclass(frozen=True)
class RuleMatch:
    """A rule hit. `matched` is the regex named group 'tag' when the pattern
    defines one (and it participated in the match), else the full matched text."""

    rule_id: str
    iso14224_class: str
    confidence: float
    matched: str


@lru_cache(maxsize=16)
def _load_rules_cached(path_str: str) -> tuple[PatternRule, ...]:
    try:
        raw = yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"pattern-rule file {path_str}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise ValueError(f"pattern-rule file {path_str}: expected a mapping with a 'rules' list")
    rules: list[PatternRule] = []
    for index, entry in enumerate(raw["rules"]):
        if not isinstance(entry, dict):
            raise ValueError(
                f"pattern-rule file {path_str}: rule at index {index} must be a mapping")
        label = entry.get("id") or f"at index {index}"
        try:
            rules.append(PatternRule(
                id=str(entry["id"]), pattern=str(entry["pattern"]),
                iso14224_class=str(entry["iso14224_class"]),
                confidence=float(entry["confidence"]), applies_to=str(entry["applies_to"])))
        except KeyError as exc:
            raise ValueError(
                f"pattern-rule file {path_str}: rule {label}: missing key {exc}") from exc
        except (TypeError, ValueError) as exc:
            # covers non-numeric confidence (float() failures) and PatternRule validation;
            # PatternRule's own ValueError already names the rule — don't prefix it twice
            prefix = "" if str(exc).startswith(f"rule {label!r}") else f"rule {label}: "
            raise ValueError(f"pattern-rule file {path_str}: {prefix}{exc}") from exc
    return tuple(rules)


def load_rules(path: Path | None = None) -> list[PatternRule]:
    """Load the rule registry (cached per resolved path). ValueError on bad rules/file."""
    if path is None:
        env = os.environ.get(_ENV_PATH)
        path = Path(env) if env else _DEFAULT_PATH
    return list(_load_rules_cached(str(path.resolve())))


def apply_rules(value: str, applies_to: str, *,
                rules: list[PatternRule] | None = None) -> RuleMatch | None:
    """Highest-confidence rule (for `applies_to`) whose regex matches `value`;
    ties break on rule order. rules=None loads the default registry."""
    if applies_to not in APPLIES_TO:
        raise ValueError(f"applies_to {applies_to!r} not in {sorted(APPLIES_TO)}")
    best: RuleMatch | None = None
    for rule in rules if rules is not None else load_rules():
        if rule.applies_to != applies_to:
            continue
        m = rule.regex.search(value)
        if m is None:
            continue
        if best is None or rule.confidence > best.confidence:
            best = RuleMatch(rule_id=rule.id, iso14224_class=rule.iso14224_class,
                             confidence=rule.confidence,
                             matched=m.groupdict().get("tag") or m.group(0))
    return best


__all__ = ["APPLIES_TO", "PatternRule", "RuleMatch", "apply_rules", "load_rules"]
