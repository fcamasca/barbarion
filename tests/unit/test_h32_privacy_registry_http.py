"""H3.2-T12.1: fetch HTTP minimo y comando de refresh explicito."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from barbarion import cli
from barbarion.infrastructure import privacy_registry_http
from barbarion.infrastructure.privacy_registry_http import (
    HttpPrivacyRegistryFetcher,
    PrivacyRegistryHttpError,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "h32_ai_provider_trust_registry.json"


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def read(self, limit: int = -1) -> bytes:
        return self.body[:limit]


def test_fetcher_uses_only_get_and_decodes_object(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, float]] = []

    def fake_urlopen(request: object, *, timeout: float) -> FakeResponse:
        calls.append((request, timeout))
        return FakeResponse(b'{"name":"AI Provider Trust Registry"}')

    monkeypatch.setattr(privacy_registry_http, "urlopen", fake_urlopen)
    result = HttpPrivacyRegistryFetcher().fetch()

    assert result["name"] == "AI Provider Trust Registry"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.full_url == privacy_registry_http.PRIVACY_REGISTRY_URL
    assert request.method == "GET"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent") == "Barbarion-PrivacyRefresh/1.0"
    assert timeout == privacy_registry_http.PRIVACY_REGISTRY_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(b"{}", status=500),
        FakeResponse(b"not-json"),
        FakeResponse(json.dumps(["not-an-object"]).encode("utf-8")),
    ],
)
def test_fetcher_rejects_http_or_json_before_cache(
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse,
) -> None:
    monkeypatch.setattr(privacy_registry_http, "urlopen", lambda *args, **kwargs: response)

    with pytest.raises(PrivacyRegistryHttpError):
        HttpPrivacyRegistryFetcher().fetch()


def test_cli_refresh_writes_normalized_atomic_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "barbarion.toml"
    config.write_text(
        '\n'.join(
            (
                'data_dir = "./data"',
                'database_path = "./data/barbarion.db"',
                'logs_dir = "./logs"',
            )
        ),
        encoding="utf-8",
    )
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    class FixtureFetcher:
        def fetch(self):  # noqa: ANN201
            return payload

    monkeypatch.setattr(cli, "HttpPrivacyRegistryFetcher", FixtureFetcher)
    assert cli.main(["--config", str(config), "privacy", "refresh"]) == 0
    captured = capsys.readouterr()

    snapshot = tmp_path / "data" / "privacy" / "registry-snapshot.json"
    assert snapshot.exists()
    assert "Privacy snapshot actualizada" in captured.out
    envelope = json.loads(snapshot.read_text(encoding="utf-8"))
    assert envelope["source_id"] == "ai-provider-trust-registry"
    assert "SYNTHETIC-CONTENT-CANARY" not in snapshot.read_text(encoding="utf-8")
