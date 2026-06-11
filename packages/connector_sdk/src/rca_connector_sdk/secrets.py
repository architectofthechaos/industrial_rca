"""Secret-ref resolution — connections store a `SecretRef` string, never the secret itself.

A SecretRef names where a secret lives, e.g. `env:PI_PASSWORD`. The resolver dereferences it
at use time. Phase 1 only supports the `env:` scheme; other schemes (e.g. `vault:`) raise
UnsupportedSecretScheme until a real broker is wired in (Track 1).
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

SecretRef = str   # "env:VAR_NAME"


class UnsupportedSecretScheme(Exception):
    """The SecretRef uses a scheme this resolver doesn't understand."""


@runtime_checkable
class SecretResolver(Protocol):
    def resolve(self, ref: SecretRef) -> str: ...


class EnvSecretResolver:
    """Resolves `env:VAR_NAME` refs from the process environment; nothing else."""

    _SCHEME = "env:"

    def resolve(self, ref: SecretRef) -> str:
        if not ref.startswith(self._SCHEME):
            scheme = ref.split(":", 1)[0] if ":" in ref else ref
            raise UnsupportedSecretScheme(
                f"unsupported secret scheme {scheme!r} in ref {ref!r}; only 'env:' is supported"
            )
        var_name = ref[len(self._SCHEME):]
        try:
            return os.environ[var_name]
        except KeyError:
            raise KeyError(
                f"secret env var {var_name!r} (from ref {ref!r}) is not set"
            ) from None


__all__ = ["SecretRef", "UnsupportedSecretScheme", "SecretResolver", "EnvSecretResolver"]
