"""H3.2-TP-025..032: cache local atomica y refresh explicito."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import barbarion.infrastructure.privacy_cache as cache_module
from barbarion.domain.privacy import InferenceExecution, InferenceTarget
from barbarion.infrastructure.privacy_cache import (
    PrivacyCacheStatus,
    PrivacyRefreshError,
    PrivacySnapshotCache,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "h32_ai_provider_trust_registry.json"
NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
TTL = timedelta(hours=24)


def _payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeFetcher:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload if payload is not None else _payload()
        self.calls = 0

    def fetch(self) -> dict[str, object]:
        self.calls += 1
        return copy.deepcopy(self.payload)


class FailingFetcher:
    def fetch(self) -> dict[str, object]:
        raise OSError("synthetic registry unavailable")


def _target(model: str = "claude-current") -> InferenceTarget:
    return InferenceTarget(
        execution=InferenceExecution.REMOTE,
        provider="anthropic",
        platform="direct_api",
        offering="anthropic-api",
        model=model,
    )


def test_tp025_explicit_refresh_writes_readable_versioned_snapshot(tmp_path: Path) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    fetcher = FakeFetcher()

    refreshed = cache.refresh(fetcher, now=NOW, ttl=TTL)
    read = cache.read(now=NOW)

    assert fetcher.calls == 1
    assert refreshed.path == tmp_path / "privacy" / "registry-snapshot.json"
    assert refreshed.source_version == "2026-08-07"
    assert read.status is PrivacyCacheStatus.VALID
    assert read.source_version == refreshed.source_version
    assert read.fetched_at == refreshed.fetched_at
    assert read.expires_at == refreshed.expires_at
    assert read.source is not None
    assert read.source.lookup(_target()).evidence


def test_tp026_valid_cache_is_read_offline_without_fetcher(tmp_path: Path) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    cache.refresh(FakeFetcher(), now=NOW, ttl=TTL)

    read = cache.read(now=NOW + timedelta(hours=1))

    assert read.status is PrivacyCacheStatus.VALID
    assert read.source is not None


def test_tp027_missing_cache_returns_local_state_only(tmp_path: Path) -> None:
    read = PrivacySnapshotCache(tmp_path).read(now=NOW)

    assert read.status is PrivacyCacheStatus.MISSING
    assert read.reason_code == "privacy_cache_missing"
    assert read.source is None


def test_tp028_expiry_boundary_and_failed_refresh_preserve_snapshot(tmp_path: Path) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    refreshed = cache.refresh(FakeFetcher(), now=NOW, ttl=TTL)
    previous = cache.path.read_bytes()

    assert cache.read(now=refreshed.expires_at).status is PrivacyCacheStatus.EXPIRED
    assert (
        cache.read(now=refreshed.expires_at + timedelta(seconds=1)).status
        is PrivacyCacheStatus.EXPIRED
    )
    with pytest.raises(PrivacyRefreshError):
        cache.refresh(FailingFetcher(), now=NOW + timedelta(hours=2), ttl=TTL)
    assert cache.path.read_bytes() == previous


def test_tp029_effective_expiry_is_minimum_of_ttl_and_source(tmp_path: Path) -> None:
    source_limited = _payload()
    source_limited["expires"] = "2026-08-07T16:00:00Z"
    first = PrivacySnapshotCache(tmp_path / "source").refresh(
        FakeFetcher(source_limited),
        now=NOW,
        ttl=TTL,
    )
    ttl_limited = PrivacySnapshotCache(tmp_path / "ttl").refresh(
        FakeFetcher(),
        now=NOW,
        ttl=timedelta(hours=2),
    )

    assert first.expires_at == NOW + timedelta(hours=4)
    assert ttl_limited.expires_at == NOW + timedelta(hours=2)


@pytest.mark.parametrize("mutation", ["schema", "integrity", "identity"])
def test_tp030_invalid_schema_integrity_or_identity_is_rejected(
    tmp_path: Path,
    mutation: str,
) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    cache.refresh(FakeFetcher(), now=NOW, ttl=TTL)
    envelope = json.loads(cache.path.read_text(encoding="utf-8"))
    if mutation == "schema":
        envelope["schema_version"] = 99
    elif mutation == "integrity":
        envelope["payload"]["generated"] = "2099-01-01"
    else:
        envelope["source_id"] = "different-registry"
    cache.path.write_text(json.dumps(envelope), encoding="utf-8")

    read = cache.read(now=NOW)

    assert read.status is PrivacyCacheStatus.INVALID
    assert read.source is None


def test_tp030_future_clock_is_invalid_even_with_intact_snapshot(tmp_path: Path) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    cache.refresh(FakeFetcher(), now=NOW, ttl=TTL)

    read = cache.read(now=NOW - timedelta(seconds=1))

    assert read.status is PrivacyCacheStatus.INVALID


def test_tp031_atomic_replace_failure_keeps_last_valid_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    cache.refresh(FakeFetcher(), now=NOW, ttl=TTL)
    previous = cache.path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"synthetic replace failure: {source} -> {destination}")

    monkeypatch.setattr(cache_module.os, "replace", fail_replace)
    with pytest.raises(PrivacyRefreshError):
        cache.refresh(FakeFetcher(), now=NOW + timedelta(hours=1), ttl=TTL)

    assert cache.path.read_bytes() == previous
    assert list(cache.path.parent.glob("*.tmp")) == []


def test_tp032_repeated_consumers_use_one_snapshot_without_refresh_correlation(
    tmp_path: Path,
) -> None:
    cache = PrivacySnapshotCache(tmp_path)
    fetcher = FakeFetcher()
    cache.refresh(fetcher, now=NOW, ttl=TTL)

    first = cache.read(now=NOW + timedelta(minutes=1))
    second = cache.read(now=NOW + timedelta(minutes=2))
    assert first.source is not None
    assert second.source is not None
    first.source.lookup(_target("first-public-model"))
    second.source.lookup(_target("second-public-model"))

    assert fetcher.calls == 1
    envelope = cache.path.read_text(encoding="utf-8")
    assert "first-public-model" not in envelope
    assert "second-public-model" not in envelope
    assert "SYNTHETIC-CONTENT-CANARY" not in envelope
