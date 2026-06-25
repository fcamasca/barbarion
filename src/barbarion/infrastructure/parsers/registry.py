"""Registro explicito extension -> parser."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath

from barbarion.domain.ports import ParserPort


class ParserRegistryError(ValueError):
    """Error de configuracion del registro de parsers."""


class DuplicateParserExtensionError(ParserRegistryError):
    """Una extension fue declarada por mas de un parser."""


class UnknownParserExtensionError(ParserRegistryError):
    """No existe parser registrado para la extension solicitada."""


class ParserRegistry:
    """Resuelve parsers por extension sin imports dinamicos."""

    def __init__(self, parsers: Iterable[ParserPort] = ()) -> None:
        self._parsers_by_extension: dict[str, ParserPort] = {}
        for parser in parsers:
            self.register(parser)

    @property
    def supported_extensions(self) -> tuple[str, ...]:
        """Extensiones conocidas, ordenadas para resultados deterministas."""

        return tuple(sorted(self._parsers_by_extension))

    @property
    def parsers(self) -> tuple[ParserPort, ...]:
        """Parsers registrados, sin duplicar instancias por extension."""

        seen: set[int] = set()
        parsers: list[ParserPort] = []
        for extension in self.supported_extensions:
            parser = self._parsers_by_extension[extension]
            parser_identity = id(parser)
            if parser_identity in seen:
                continue
            seen.add(parser_identity)
            parsers.append(parser)
        return tuple(parsers)

    def register(self, parser: ParserPort) -> None:
        """Registra un parser y rechaza extensiones repetidas."""

        parser_id = _require_non_empty(parser.parser_id, "parser_id")
        _require_non_empty(parser.parser_version, "parser_version")
        extensions = tuple(
            _normalize_extension(extension)
            for extension in parser.supported_extensions
        )
        if not extensions:
            raise ParserRegistryError(
                f"El parser {parser_id} debe declarar al menos una extension."
            )

        duplicated_within_parser = _first_duplicate(extensions)
        if duplicated_within_parser is not None:
            raise DuplicateParserExtensionError(
                "La extension "
                f"{duplicated_within_parser} esta duplicada en el parser {parser_id}."
            )

        for extension in extensions:
            existing_parser = self._parsers_by_extension.get(extension)
            if existing_parser is None:
                continue
            raise DuplicateParserExtensionError(
                "La extension "
                f"{extension} ya esta registrada por {existing_parser.parser_id}."
            )

        for extension in extensions:
            self._parsers_by_extension[extension] = parser

    def resolve(self, value: str | PurePath) -> ParserPort:
        """Devuelve el parser asociado a una extension o ruta."""

        extension = _extension_from(value)
        parser = self._parsers_by_extension.get(extension)
        if parser is None:
            raise UnknownParserExtensionError(
                f"No hay parser registrado para la extension {extension}."
            )
        return parser


def _extension_from(value: str | PurePath) -> str:
    if isinstance(value, PurePath):
        extension = value.suffix
    else:
        text = _require_non_empty(value, "extension")
        path_suffix = PurePath(text).suffix
        extension = path_suffix if path_suffix else text
    return _normalize_extension(extension)


def _normalize_extension(value: str) -> str:
    extension = _require_non_empty(value, "extension").lower()
    if not extension.startswith("."):
        extension = f".{extension}"
    if extension == "." or "/" in extension or "\\" in extension:
        raise ParserRegistryError("La extension del parser no es valida.")
    return extension


def _require_non_empty(value: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParserRegistryError(f"{key} debe ser una cadena no vacia.")
    return value.strip()


def _first_duplicate(values: tuple[str, ...]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None
