"""Versioned prompt registry (Sprint 3 WI1).

Prompts are Markdown files with a YAML frontmatter header declaring ``name``, ``version``,
``model``, ``temperature``, ``max_tokens``, ``variables`` and an optional ``output_schema``
(JSON Schema). At load the registry validates that (a) the frontmatter is well-formed, (b)
every ``{{ var }}`` referenced in the body is declared in ``variables`` and vice-versa, and
(c) ``output_schema`` is a valid JSON Schema. Rendering is a dependency-free ``{{ var }}``
substitution (jinja2 is not a product dependency).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptValidationError(ValueError):
    pass


class Prompt(BaseModel):
    name: str
    version: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 2000
    variables: list[str] = Field(default_factory=list)
    output_schema: dict | None = None
    body: str

    def referenced_variables(self) -> set[str]:
        return set(_VAR_RE.findall(self.body))

    def render(self, variables: dict[str, Any]) -> str:
        missing = set(self.variables) - set(variables)
        if missing:
            raise PromptValidationError(
                f"prompt {self.name}/{self.version} missing variables: {sorted(missing)}")

        def _sub(match: re.Match[str]) -> str:
            return str(variables[match.group(1)])

        return _VAR_RE.sub(_sub, self.body)


def parse_prompt(text: str, *, source: str = "<string>") -> Prompt:
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        raise PromptValidationError(f"{source}: missing YAML frontmatter (--- ... ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    body = m.group(2)
    if not isinstance(meta, dict):
        raise PromptValidationError(f"{source}: frontmatter must be a mapping")
    for required in ("name", "version", "model"):
        if required not in meta:
            raise PromptValidationError(f"{source}: frontmatter missing {required!r}")
    prompt = Prompt(**meta, body=body)

    declared = set(prompt.variables)
    referenced = prompt.referenced_variables()
    if referenced - declared:
        raise PromptValidationError(
            f"{source}: body references undeclared variables: {sorted(referenced - declared)}")
    if declared - referenced:
        raise PromptValidationError(
            f"{source}: declared variables never used in body: {sorted(declared - referenced)}")
    if prompt.output_schema is not None:
        try:
            Draft202012Validator.check_schema(prompt.output_schema)
        except Exception as exc:  # noqa: BLE001
            raise PromptValidationError(f"{source}: invalid output_schema: {exc}") from exc
    return prompt


class PromptRegistry:
    """Loads prompts at startup, validates, and exposes ``get_prompt(name, version)``."""

    def __init__(self, prompts: dict[tuple[str, str], Prompt] | None = None) -> None:
        self._prompts: dict[tuple[str, str], Prompt] = dict(prompts or {})

    @classmethod
    def from_directory(cls, directory: str | Path) -> "PromptRegistry":
        directory = Path(directory)
        prompts: dict[tuple[str, str], Prompt] = {}
        for path in sorted(directory.glob("*.md")):
            prompt = parse_prompt(path.read_text(), source=str(path))
            key = (prompt.name, prompt.version)
            if key in prompts:
                raise PromptValidationError(f"duplicate prompt {key}")
            prompts[key] = prompt
        return cls(prompts)

    def add(self, prompt: Prompt) -> None:
        self._prompts[(prompt.name, prompt.version)] = prompt

    def get_prompt(self, name: str, version: str) -> Prompt:
        try:
            return self._prompts[(name, version)]
        except KeyError:
            raise KeyError(f"no prompt {name!r} version {version!r} in registry") from None

    def names(self) -> list[tuple[str, str]]:
        return sorted(self._prompts)


def default_registry() -> PromptRegistry:
    """Registry loaded from the packaged ``prompts/`` directory."""
    return PromptRegistry.from_directory(Path(__file__).parent / "prompts")


__all__ = [
    "Prompt", "PromptRegistry", "PromptValidationError", "parse_prompt", "default_registry",
]
