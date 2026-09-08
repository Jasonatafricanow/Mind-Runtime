import sys

import pytest

from tests.memory_vector.test_contracts import identity


def test_fastembed_missing_package_is_explicit(tmp_path, monkeypatch):
    from mind_runtime.memory.providers.errors import ProviderPackageMissing
    from mind_runtime.memory.providers.fastembed import FastEmbedEmbedding

    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(ProviderPackageMissing):
        FastEmbedEmbedding(identity(provider="fastembed"), model_dir=tmp_path)


def test_fastembed_missing_model_cannot_download(tmp_path, monkeypatch):
    from fastembed import TextEmbedding

    from mind_runtime.memory.providers.errors import ProviderStorageUnavailable
    from mind_runtime.memory.providers.fastembed import FastEmbedEmbedding

    monkeypatch.setattr(TextEmbedding, "__init__", lambda *a, **kw: pytest.fail("unexpected load"))
    with pytest.raises(ProviderStorageUnavailable):
        FastEmbedEmbedding(identity(provider="fastembed"), model_dir=tmp_path / "absent")
    assert list(tmp_path.iterdir()) == []


def test_model_fingerprint_is_content_bound(tmp_path):
    from mind_runtime.memory.providers.fastembed import model_revision

    (tmp_path / "model.onnx").write_bytes(b"model")
    (tmp_path / "tokenizer.json").write_text("{}")
    one = model_revision(tmp_path)
    (tmp_path / "tokenizer.json").write_text('{"different":true}')
    assert model_revision(tmp_path) != one


def test_model_identity_mismatch_before_loading(tmp_path, monkeypatch):
    from fastembed import TextEmbedding

    from mind_runtime.memory.providers.errors import ProviderStorageUnavailable
    from mind_runtime.memory.providers.fastembed import FastEmbedEmbedding

    (tmp_path / "model.onnx").write_bytes(b"model")
    monkeypatch.setattr(TextEmbedding, "__init__", lambda *a, **kw: pytest.fail("unexpected load"))
    with pytest.raises(ProviderStorageUnavailable):
        FastEmbedEmbedding(identity(provider="fastembed"), model_dir=tmp_path)
