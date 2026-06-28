"""Pruebas de proveedores de embeddings H3."""

import urllib.error
from typing import Any

import pytest

from barbarion.domain.rag import (
    EmbeddingProviderError,
    EmbeddingRequest,
    embedding_version,
)
from barbarion.infrastructure.embeddings import (
    DeterministicFakeEmbeddingProvider,
    OllamaEmbeddingProvider,
)


VERSION = embedding_version(
    provider="fake",
    model="sha256",
    dimension=8,
    distance="cosine",
    normalize=True,
)


def test_fake_embedding_provider_is_deterministic() -> None:
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    request = EmbeddingRequest(
        texts=("select order_total from dual",),
        input_kind="chunk",
        embedding_version=VERSION,
    )

    first = provider.embed(request)
    second = provider.embed(request)

    assert first == second
    assert first[0].dimension == 8
    assert first[0].provider == "fake"
    assert first[0].model == "sha256"


def test_fake_embedding_provider_changes_when_text_changes() -> None:
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    first = provider.embed(
        EmbeddingRequest(("texto original",), "chunk", VERSION)
    )
    second = provider.embed(
        EmbeddingRequest(("texto modificado",), "chunk", VERSION)
    )

    assert first[0].values != second[0].values


class FakeResponse:
    """Respuesta HTTP falsa para Ollama."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self) -> bytes:
        return self.body


class FakeOpener:
    """Opener fake compatible con urllib."""

    def __init__(self, responses: list[bytes]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        return FakeResponse(self.responses.pop(0))


def test_ollama_embedding_provider_reads_embeddings() -> None:
    opener = FakeOpener(
        [
            b'{"embedding":[0.1,0.2,0.3]}',
            b'{"embedding":[0.4,0.5,0.6]}',
        ]
    )
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        timeout_seconds=5,
        _opener=opener,
    )

    vectors = provider.embed(
        EmbeddingRequest(("uno", "dos"), "query", "a" * 64)
    )

    assert [vector.text_index for vector in vectors] == [0, 1]
    assert vectors[0].values == (0.1, 0.2, 0.3)
    assert vectors[1].values == (0.4, 0.5, 0.6)
    assert len(opener.requests) == 2


def test_ollama_embedding_provider_rejects_dimension_mismatch() -> None:
    opener = FakeOpener(
        [
            b'{"embedding":[0.1,0.2,0.3]}',
            b'{"embedding":[0.4,0.5]}',
        ]
    )
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        timeout_seconds=5,
        _opener=opener,
    )

    with pytest.raises(EmbeddingProviderError, match="DIMENSION"):
        provider.embed(EmbeddingRequest(("uno", "dos"), "query", "a" * 64))


class FailingOpener:
    """Opener que simula fallo de red."""

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        del request, timeout
        raise urllib.error.URLError("offline")


def test_ollama_embedding_provider_reports_unavailable() -> None:
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        timeout_seconds=5,
        _opener=FailingOpener(),
    )

    with pytest.raises(EmbeddingProviderError, match="UNAVAILABLE"):
        provider.embed(EmbeddingRequest(("uno",), "query", "a" * 64))


def test_ollama_embedding_provider_rejects_invalid_response() -> None:
    opener = FakeOpener([b'{"not_embedding":[]}'])
    provider = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:11434",
        model="nomic-embed-text",
        timeout_seconds=5,
        _opener=opener,
    )

    with pytest.raises(EmbeddingProviderError, match="RESPONSE_INVALID"):
        provider.embed(EmbeddingRequest(("uno",), "query", "a" * 64))
