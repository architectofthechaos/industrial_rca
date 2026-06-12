from rca_llm import embedding_config as ec


def test_default_model_and_dims(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    assert ec.embedding_model() == "voyage-3"
    assert ec.embedding_dim() == 1024


def test_env_override(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "voyage-3-lite")
    monkeypatch.setenv("EMBEDDING_DIM", "512")
    assert ec.embedding_model() == "voyage-3-lite"
    assert ec.embedding_dim() == 512
