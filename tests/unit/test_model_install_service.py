"""Pruebas del caso de uso de instalacion de modelos."""

from collections.abc import Callable

import pytest

from barbarion.application.local_models import InstallModelService
from barbarion.domain.local_models import (
    LocalModel,
    LocalModelErrorCode,
    LocalModelProviderError,
    PullProgress,
    PullResult,
)


class FakeInstallProvider:
    def __init__(self, listings: list[tuple[LocalModel, ...]]) -> None:
        self.listings = list(listings)
        self.calls: list[tuple[object, ...]] = []

    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        self.calls.append(("list", timeout_seconds))
        return self.listings.pop(0)

    def pull_model(
        self,
        name: str,
        *,
        timeout_seconds: float,
        on_progress: Callable[[PullProgress], None] | None = None,
    ) -> PullResult:
        self.calls.append(("pull", name, timeout_seconds))
        if on_progress is not None:
            on_progress(PullProgress("downloading", completed=5, total=10))
            on_progress(PullProgress("success"))
        return PullResult(name, "success")


def test_install_skips_pull_when_model_is_already_installed() -> None:
    provider = FakeInstallProvider([ (LocalModel("modelo:tag"),) ])

    result = InstallModelService(provider).run(
        "modelo:tag",
        timeout_seconds=30,
    )

    assert result.already_installed is True
    assert result.pull_requested is False
    assert result.final_present is True
    assert provider.calls == [("list", 30)]


def test_install_dry_run_reports_missing_without_pull() -> None:
    provider = FakeInstallProvider([()])

    result = InstallModelService(provider).run(
        "modelo:tag",
        timeout_seconds=30,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.pull_requested is False
    assert result.final_present is False
    assert provider.calls == [("list", 30)]


def test_install_pulls_emits_progress_and_confirms_final_presence() -> None:
    provider = FakeInstallProvider([(), (LocalModel("modelo:tag"),)])
    progress: list[PullProgress] = []

    result = InstallModelService(provider).run(
        "modelo:tag",
        timeout_seconds=60,
        on_progress=progress.append,
    )

    assert result.pull_requested is True
    assert result.final_present is True
    assert result.final_status == "success"
    assert [item.status for item in progress] == ["downloading", "success"]
    assert provider.calls == [
        ("list", 60),
        ("pull", "modelo:tag", 60),
        ("list", 60),
    ]


def test_install_fails_when_final_presence_cannot_be_confirmed() -> None:
    provider = FakeInstallProvider([(), ()])

    with pytest.raises(LocalModelProviderError) as captured:
        InstallModelService(provider).run("modelo:tag", timeout_seconds=60)

    assert captured.value.code is LocalModelErrorCode.OPERATION_FAILED
    assert "no reporta el modelo instalado" in captured.value.detail


@pytest.mark.parametrize("name", [" ", "https://example.invalid/model", "bad\nname"])
def test_install_rejects_invalid_identifier_before_contacting_provider(
    name: str,
) -> None:
    provider = FakeInstallProvider([])

    with pytest.raises(ValueError, match="identificador"):
        InstallModelService(provider).run(name, timeout_seconds=60)

    assert provider.calls == []
