"""Proveedores locales de embeddings para H3."""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from barbarion.domain.rag import (
    EmbeddingProviderError,
    EmbeddingRequest,
    EmbeddingVector,
)


@dataclass(frozen=True, slots=True)
class DeterministicFakeEmbeddingProvider:
    """Proveedor fake 100 % determinista basado en SHA-256 del texto."""

    dimension: int = 8
    provider: str = "fake"
    model: str = "sha256"
    normalize: bool = True

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            raise ValueError("dimension debe ser mayor que 0.")

    def embed(self, request: EmbeddingRequest) -> tuple[EmbeddingVector, ...]:
        """Genera un vector estable para cada texto del batch."""
        return tuple(
            EmbeddingVector(
                text_index=index,
                values=self._vector_for_text(text),
                provider=self.provider,
                model=self.model,
            )
            for index, text in enumerate(request.texts)
        )

    def _vector_for_text(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw_values: list[float] = []
        counter = 0
        while len(raw_values) < self.dimension:
            block = hashlib.sha256(
                digest + counter.to_bytes(4, byteorder="big")
            ).digest()
            raw_values.extend((byte / 255.0) for byte in block)
            counter += 1
        values = tuple(raw_values[: self.dimension])
        if not self.normalize:
            return values
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return tuple(value / norm for value in values)


@dataclass(frozen=True, slots=True)
class OllamaEmbeddingProvider:
    """Adaptador local para embeddings de Ollama."""

    base_url: str
    model: str
    timeout_seconds: float
    provider: str = "ollama"
    _opener: object | None = field(default=None, repr=False, compare=False)

    def embed(self, request: EmbeddingRequest) -> tuple[EmbeddingVector, ...]:
        """Genera embeddings llamando al endpoint local de Ollama."""
        vectors: list[EmbeddingVector] = []
        expected_dimension: int | None = None
        for index, text in enumerate(request.texts):
            values = self._embed_one(text)
            if expected_dimension is None:
                expected_dimension = len(values)
            elif len(values) != expected_dimension:
                raise EmbeddingProviderError(
                    "OLLAMA_EMBEDDING_DIMENSION_MISMATCH: Ollama devolvio "
                    "dimensiones inconsistentes."
                )
            vectors.append(
                EmbeddingVector(
                    text_index=index,
                    values=values,
                    provider=self.provider,
                    model=self.model,
                )
            )
        return tuple(vectors)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        payload = json.dumps(
            {"model": self.model, "prompt": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            if self._opener is None:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    raw_body = response.read()
            else:
                response = self._opener.open(  # type: ignore[attr-defined]
                    request,
                    timeout=self.timeout_seconds,
                )
                with response:
                    raw_body = response.read()
        except urllib.error.URLError as error:
            raise EmbeddingProviderError(
                "OLLAMA_EMBEDDINGS_UNAVAILABLE: no se pudo contactar Ollama "
                "local para generar embeddings."
            ) from error

        try:
            body = json.loads(raw_body.decode("utf-8"))
            embedding = body["embedding"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise EmbeddingProviderError(
                "OLLAMA_EMBEDDING_RESPONSE_INVALID: Ollama devolvio una "
                "respuesta invalida."
            ) from error

        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingProviderError(
                "OLLAMA_EMBEDDING_RESPONSE_INVALID: embedding vacio o invalido."
            )
        values: list[float] = []
        for value in embedding:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingProviderError(
                    "OLLAMA_EMBEDDING_RESPONSE_INVALID: dimension no numerica."
                )
            values.append(float(value))
        return tuple(values)
