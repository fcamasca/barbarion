from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from barbarion.domain.models import (
    ExtractionContext,
    ExtractionResult,
    SourceFile,
)
from barbarion.infrastructure.parsers import BaseParser
from barbarion.infrastructure.parsers.registry import (
    DuplicateParserExtensionError,
    ParserRegistry,
    ParserRegistryError,
    UnknownParserExtensionError,
)


class FakeParser(BaseParser):
    parser_id = "fake"
    parser_version = "1"
    supported_extensions = (".sql", "PKB")

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        return ExtractionResult(
            text="contenido",
            title="fake",
            encoding=context.encodings[0],
        )


class MarkdownParser(BaseParser):
    parser_id = "markdown"
    parser_version = "1"
    supported_extensions = (".md",)

    def extract(
        self,
        source: SourceFile,
        context: ExtractionContext,
    ) -> ExtractionResult:
        return ExtractionResult(text="# titulo", title="titulo", encoding="utf-8")


def test_registry_resolves_by_extension_and_path() -> None:
    parser = FakeParser()
    registry = ParserRegistry([parser])

    assert registry.resolve(".SQL") is parser
    assert registry.resolve("pkb") is parser
    assert registry.resolve(PurePosixPath("pkg/body.PKB")) is parser
    assert registry.supported_extensions == (".pkb", ".sql")


def test_registry_keeps_unique_parser_instances() -> None:
    fake_parser = FakeParser()
    markdown_parser = MarkdownParser()
    registry = ParserRegistry([fake_parser, markdown_parser])

    assert registry.parsers == (markdown_parser, fake_parser)


def test_registry_rejects_duplicate_extension_between_parsers() -> None:
    class OtherSqlParser(MarkdownParser):
        parser_id = "other_sql"
        supported_extensions = (".SQL",)

    with pytest.raises(DuplicateParserExtensionError, match="ya esta registrada"):
        ParserRegistry([FakeParser(), OtherSqlParser()])


def test_registry_rejects_duplicate_extension_in_same_parser() -> None:
    class DuplicatedParser(MarkdownParser):
        parser_id = "duplicated"
        supported_extensions = (".md", "MD")

    with pytest.raises(DuplicateParserExtensionError, match="duplicada"):
        ParserRegistry([DuplicatedParser()])


def test_registry_rejects_unknown_extension() -> None:
    registry = ParserRegistry([FakeParser()])

    with pytest.raises(UnknownParserExtensionError, match=".txt"):
        registry.resolve(".txt")


def test_registry_rejects_invalid_parser_contract() -> None:
    class NoExtensionsParser(MarkdownParser):
        parser_id = "empty"
        supported_extensions: tuple[str, ...] = ()

    with pytest.raises(ParserRegistryError, match="al menos una extension"):
        ParserRegistry([NoExtensionsParser()])


def test_base_parser_requires_extract_implementation() -> None:
    class IncompleteParser(BaseParser):
        parser_id = "incomplete"
        parser_version = "1"
        supported_extensions = (".txt",)

    with pytest.raises(TypeError):
        IncompleteParser()
