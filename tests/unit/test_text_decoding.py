from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from barbarion.infrastructure.parsers.encoding import (
    LOW_CONFIDENCE_ENCODING,
    TEXT_DECODE_FAILED,
    TextExtractionError,
    decode_text_bytes,
)


RELATIVE_PATH = PurePosixPath("docs/sample.txt")


def decode(raw: bytes, encodings: tuple[str, ...] = ("cp1252", "latin-1")):
    return decode_text_bytes(
        raw,
        encodings=encodings,
        relative_path=RELATIVE_PATH,
    )


def test_decode_respects_utf8_bom() -> None:
    decoded = decode(b"\xef\xbb\xbfHola")

    assert decoded.text == "Hola"
    assert decoded.encoding == "utf-8"
    assert decoded.warnings == ()


@pytest.mark.parametrize(
    ("raw", "expected_encoding"),
    [
        ("Linea".encode("utf-16-le"), "utf-16-le"),
        ("Linea".encode("utf-16-be"), "utf-16-be"),
    ],
)
def test_decode_respects_utf16_bom(raw: bytes, expected_encoding: str) -> None:
    bom = b"\xff\xfe" if expected_encoding == "utf-16-le" else b"\xfe\xff"

    decoded = decode(bom + raw)

    assert decoded.text == "Linea"
    assert decoded.encoding == expected_encoding


def test_decode_tries_strict_utf8_before_fallbacks() -> None:
    decoded = decode("año".encode("utf-8"), encodings=("cp1252",))

    assert decoded.text == "año"
    assert decoded.encoding == "utf-8"


def test_decode_uses_configured_cp1252_fallback() -> None:
    decoded = decode("Precio €".encode("cp1252"), encodings=("cp1252",))

    assert decoded.text == "Precio €"
    assert decoded.encoding == "cp1252"


def test_decode_latin1_adds_warning() -> None:
    decoded = decode(b"Control \x81", encodings=("cp1252", "latin-1"))

    assert decoded.text == "Control \x81"
    assert decoded.encoding == "latin-1"
    assert decoded.warnings == (LOW_CONFIDENCE_ENCODING,)


def test_decode_failure_is_typed_without_replacement() -> None:
    with pytest.raises(TextExtractionError) as raised:
        decode(b"\xff", encodings=("utf-8",))

    error = raised.value.to_pipeline_error()
    assert error.error_code == TEXT_DECODE_FAILED
    assert error.relative_path == RELATIVE_PATH
    assert error.details["attempted_encodings"] == ["utf-8"]


def test_decode_corrupt_bom_failure_is_typed() -> None:
    with pytest.raises(TextExtractionError) as raised:
        decode(b"\xff\xfe\x00", encodings=("utf-8",))

    error = raised.value.to_pipeline_error()
    assert error.error_code == TEXT_DECODE_FAILED
    assert error.details["encoding"] == "utf-16-le"
