"""Pruebas de puertos minimos del dominio de ingesta."""

from pathlib import Path, PurePosixPath

from barbarion.domain.models import (
    Confidence,
    DiscoveredFile,
    ExtractionContext,
    ExtractionResult,
    FileFingerprint,
    IngestionMetrics,
    IngestionMode,
    IngestionOutcome,
    IngestionRunStatus,
    LogicalUnit,
    NormalizedDocument,
    SourceFile,
)
from barbarion.domain.ports import ParserPort
from barbarion.domain.ports import EmbeddingProviderPort
from barbarion.domain.rag import EmbeddingRequest, EmbeddingVector


VALID_SHA = "a" * 64


class FakeParser:
    """Parser de prueba que satisface el protocolo sin infraestructura."""

    parser_id = "fake"
    parser_version = "1"
    supported_extensions = (".sql",)

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        return ExtractionResult(
            text=f"-- {source.discovered.relative_path}",
            title=None,
            encoding=context.encodings[0],
            units=(LogicalUnit("file", None, Confidence.LOW),),
        )


def test_parser_port_accepts_structural_implementation(tmp_path: Path) -> None:
    parser: ParserPort = FakeParser()
    source = SourceFile(
        discovered=DiscoveredFile(
            root=tmp_path,
            relative_path=PurePosixPath("demo.sql"),
            runtime_path=tmp_path / "demo.sql",
            extension=".sql",
            size_bytes=12,
            mtime_ns=123,
        ),
        fingerprint=FileFingerprint(12, 123, VALID_SHA),
    )

    result = parser.extract(
        source,
        ExtractionContext(
            encodings=("utf-8",),
            max_extracted_chars=1000,
            max_pdf_pages=10,
        ),
    )

    assert parser.supported_extensions == (".sql",)
    assert result.encoding == "utf-8"
    assert result.units[0].confidence == Confidence.LOW


def test_repository_related_models_compose_without_adapters() -> None:
    unit = LogicalUnit("file", None, Confidence.LOW)
    document = NormalizedDocument(
        text="select 1;",
        units=(unit,),
        source_sha256=VALID_SHA,
        content_sha256=VALID_SHA,
    )
    outcome = IngestionOutcome(
        status=IngestionRunStatus.COMPLETED,
        metrics=IngestionMetrics(processed_files=1, chunk_count=1),
    )

    assert document.content_sha256 == VALID_SHA
    assert outcome.status == IngestionRunStatus.COMPLETED
    assert IngestionMode.INCREMENTAL.value == "incremental"


class FakeEmbeddingProvider:
    """Proveedor de embeddings de prueba estructural."""

    provider = "fake"
    model = "fake-model"

    def embed(self, request: EmbeddingRequest) -> tuple[EmbeddingVector, ...]:
        return tuple(
            EmbeddingVector(
                text_index=index,
                values=(float(index), 1.0),
                provider=self.provider,
                model=self.model,
            )
            for index, _text in enumerate(request.texts)
        )


def test_embedding_provider_port_accepts_structural_implementation() -> None:
    provider: EmbeddingProviderPort = FakeEmbeddingProvider()

    vectors = provider.embed(
        EmbeddingRequest(
            texts=("uno", "dos"),
            input_kind="query",
            embedding_version=VALID_SHA,
        )
    )

    assert [vector.text_index for vector in vectors] == [0, 1]
    assert vectors[0].dimension == 2

