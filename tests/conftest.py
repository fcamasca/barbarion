"""Guardas globales para que la suite normal permanezca offline."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def block_external_network(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Bloquea conexiones externas y conserva servidores loopback de prueba."""
    real_create_connection = socket.create_connection

    def guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001, ANN202
        host = address[0]
        if not _is_loopback_host(host):
            raise AssertionError(
                f"La suite offline bloqueo una conexion externa a {host!r}."
            )
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    yield


def _is_loopback_host(host: object) -> bool:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    normalized = host.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
