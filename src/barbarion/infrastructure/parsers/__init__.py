"""Parsers locales y registro explicito de ingesta."""

from barbarion.infrastructure.parsers.base import BaseParser
from barbarion.infrastructure.parsers.registry import (
    DuplicateParserExtensionError,
    ParserRegistry,
    ParserRegistryError,
    UnknownParserExtensionError,
)

__all__ = [
    "BaseParser",
    "DuplicateParserExtensionError",
    "ParserRegistry",
    "ParserRegistryError",
    "UnknownParserExtensionError",
]
