"""EnvSecretResolver: resolves env: refs, clear error on missing var, rejects other schemes."""
import pytest

from rca_connector_sdk import EnvSecretResolver, UnsupportedSecretScheme


def test_resolves_env_ref(monkeypatch):
    monkeypatch.setenv("FOO", "s3cret")
    assert EnvSecretResolver().resolve("env:FOO") == "s3cret"


def test_missing_env_var_raises_clear_error(monkeypatch):
    monkeypatch.delenv("MISSING_SECRET", raising=False)
    with pytest.raises(KeyError) as exc:
        EnvSecretResolver().resolve("env:MISSING_SECRET")
    assert "MISSING_SECRET" in str(exc.value)


def test_non_env_scheme_raises_unsupported():
    with pytest.raises(UnsupportedSecretScheme):
        EnvSecretResolver().resolve("vault:secret/path")
