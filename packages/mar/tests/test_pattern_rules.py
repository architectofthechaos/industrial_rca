"""Pattern-rule registry — single source of truth for tag/template heuristics (Sprint 2a §1.5)."""
import re

import pytest

from rca_mar.pattern_rules import PatternRule, RuleMatch, apply_rules, load_rules


def test_default_rules_load_from_yaml():
    rules = load_rules()
    ids = {r.id for r in rules}
    assert {"rule:pump_p_tag", "rule:pump_template_name"} <= ids


def test_template_rule_wins_on_template():
    m = apply_rules("centrifugal_pump", "template")
    assert m == RuleMatch(rule_id="rule:pump_template_name",
                          iso14224_class="pump.centrifugal", confidence=0.95,
                          matched="centrifugal_pump")


def test_tag_rule_matches_pump_tags():
    assert apply_rules("P-101A", "tag").rule_id == "rule:pump_p_tag"
    assert apply_rules("XV-3001", "tag") is None


def test_highest_confidence_rule_wins():
    rules = [
        PatternRule(id="rule:a", pattern="^P-.*", iso14224_class="x",
                    confidence=0.5, applies_to="tag"),
        PatternRule(id="rule:b", pattern="^P-101A$", iso14224_class="y",
                    confidence=0.9, applies_to="tag"),
    ]
    assert apply_rules("P-101A", "tag", rules=rules).rule_id == "rule:b"


def test_confidence_tie_breaks_on_file_order():
    rules = [
        PatternRule(id="rule:first", pattern="^P-", iso14224_class="x",
                    confidence=0.8, applies_to="tag"),
        PatternRule(id="rule:second", pattern="101A$", iso14224_class="y",
                    confidence=0.8, applies_to="tag"),
    ]
    assert apply_rules("P-101A", "tag", rules=rules).rule_id == "rule:first"


def test_named_tag_group_is_extracted_else_full_match():
    rules = [PatternRule(id="rule:dotted", pattern=r"[A-Z]+\.(?P<tag>[A-Z]-\d+[A-Z]?)\.",
                         iso14224_class="pump.centrifugal", confidence=0.7, applies_to="tag")]
    m = apply_rules("SITE.P-101A.PV", "tag", rules=rules)
    assert m is not None and m.matched == "P-101A"          # named group wins
    bare = [PatternRule(id="rule:bare", pattern=r"^P-\d{3}[A-Z]?$",
                        iso14224_class="pump.centrifugal", confidence=0.7, applies_to="tag")]
    m = apply_rules("P-101A", "tag", rules=bare)
    assert m is not None and m.matched == "P-101A"          # whole match otherwise


def test_bad_applies_to_and_confidence_rejected():
    with pytest.raises(ValueError):
        PatternRule(id="rule:bad", pattern="x", iso14224_class="x",
                    confidence=0.5, applies_to="serial_number")
    with pytest.raises(ValueError):
        PatternRule(id="rule:bad", pattern="x", iso14224_class="x",
                    confidence=0.0, applies_to="tag")
    with pytest.raises(ValueError):
        PatternRule(id="rule:bad", pattern="x", iso14224_class="x",
                    confidence=1.5, applies_to="tag")
    with pytest.raises(ValueError):
        PatternRule(id="rule:bad", pattern="(unbalanced", iso14224_class="x",
                    confidence=0.5, applies_to="tag")


def test_env_override_and_bad_file_rejected(tmp_path, monkeypatch):
    good = tmp_path / "rules.yaml"
    good.write_text("version: 1\n"
                    "rules:\n"
                    "  - id: rule:env_only\n"
                    "    pattern: '^E-\\d+$'\n"
                    "    iso14224_class: exchanger.shell_tube\n"
                    "    confidence: 0.8\n"
                    "    applies_to: tag\n")
    monkeypatch.setenv("MAR_PATTERN_RULES_PATH", str(good))
    assert [r.id for r in load_rules()] == ["rule:env_only"]

    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nrules:\n  - id: rule:broken\n    pattern: 'x'\n")
    with pytest.raises(ValueError, match="rule:broken"):   # names the offending rule
        load_rules(bad)


def test_corrupt_yaml_raises_valueerror_naming_the_file(tmp_path):
    corrupt = tmp_path / "corrupt.yaml"
    corrupt.write_text("rules:\n  - id: [unclosed\n")
    with pytest.raises(ValueError, match=re.escape(corrupt.name)):
        load_rules(corrupt)


def test_non_numeric_confidence_names_the_offending_rule(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("version: 1\n"
                 "rules:\n"
                 "  - id: rule:bad_conf\n"
                 "    pattern: '^X$'\n"
                 "    iso14224_class: x\n"
                 "    confidence: very high\n"
                 "    applies_to: tag\n")
    with pytest.raises(ValueError, match="rule:bad_conf"):
        load_rules(f)


def test_non_mapping_rule_entry_names_its_index(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("version: 1\nrules:\n  - just-a-string\n")
    with pytest.raises(ValueError, match="index 0"):
        load_rules(f)


def test_rule_validation_error_names_the_rule_exactly_once(tmp_path):
    """PatternRule's own ValueError already says `rule 'rule:x':` — the loader must
    not stack a second `rule rule:x:` prefix on top of it."""
    f = tmp_path / "rules.yaml"
    f.write_text("version: 1\n"
                 "rules:\n"
                 "  - id: rule:bad_pattern\n"
                 "    pattern: '(unbalanced'\n"
                 "    iso14224_class: x\n"
                 "    confidence: 0.5\n"
                 "    applies_to: tag\n")
    with pytest.raises(ValueError) as excinfo:
        load_rules(f)
    assert str(excinfo.value).count("rule:bad_pattern") == 1
