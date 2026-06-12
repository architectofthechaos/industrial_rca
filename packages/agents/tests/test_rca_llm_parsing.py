"""Robust parsing of real-LLM structured output in the RCA agent (Sprint 5 G25).

Anthropic does not hard-enforce a prompt's JSON schema, so the live LLM emitted gap questions
keyed ``{id, topic, question}`` while the code indexed ``q["text"]`` -> KeyError crashed the RCA
leg (the scripted hermetic LLM always produced the declared ``{text, question_type}`` shape).
``_question_text`` tolerates the common key variants; empty/text-less items are dropped.
"""
from __future__ import annotations

from rca_agents.rca_graph import _one_of, _question_text


def test_one_of_canonicalizes_case_insensitively():
    # the live LLM emits e.g. category "machine" / "MACHINE" for the 6M Literal
    cats = ("Manpower", "Method", "Machine", "Material", "Measurement", "Environment")
    assert _one_of("machine", cats, "Method") == "Machine"
    assert _one_of("MACHINE", cats, "Method") == "Machine"


def test_one_of_defaults_on_out_of_vocab_or_missing():
    qtypes = ("clarification", "context", "scope", "approval")
    assert _one_of("maintenance_history", qtypes, "context") == "context"   # the live crash
    assert _one_of(None, qtypes, "context") == "context"
    assert _one_of(123, qtypes, "context") == "context"


def test_question_text_accepts_question_key():
    # the exact shape the live LLM returned
    q = {"id": "q1", "topic": "maintenance_history",
         "question": "Provide the recent work-order history for P-101A."}
    assert _question_text(q) == "Provide the recent work-order history for P-101A."


def test_question_text_prefers_explicit_text():
    assert _question_text({"text": "T", "question": "Q"}) == "T"


def test_question_text_handles_variants():
    assert _question_text({"gap": "G"}) == "G"
    assert _question_text({"description": "D"}) == "D"


def test_question_text_none_when_absent():
    assert _question_text({"topic": "x"}) is None
    assert _question_text({"text": ""}) is None
