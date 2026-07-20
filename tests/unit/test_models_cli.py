"""Pruebas unitarias de vistas y renderers CLI de modelos locales."""

import json

from barbarion import cli
from barbarion.application.local_models import (
    ListModelsService,
    ModelDetailsView,
    ModelListResult,
    ShowModelService,
)
from barbarion.domain.local_models import LocalModel, LocalModelDetails


class FakeProvider:
    def list_models(self, *, timeout_seconds: float):  # noqa: ANN201
        assert timeout_seconds == 2
        return (
            LocalModel("zeta", digest="z" * 300),
            LocalModel("Alpha", size_bytes=10, modified_at="2026-07-20"),
        )

    def show_model(self, name: str, *, timeout_seconds: float):  # noqa: ANN201
        assert timeout_seconds == 2
        return LocalModelDetails(
            LocalModel(name),
            format="f" * 300,
            family="generic\nfamily",
            capabilities=tuple(f"cap-{index}" for index in range(25)),
        )


def test_list_service_orders_and_bounds_optional_metadata() -> None:
    result = ListModelsService(FakeProvider(), "Alpha").run(timeout_seconds=2)

    assert [item.name for item in result.models] == ["Alpha", "zeta"]
    assert result.active_model_installed is True
    assert result.models[0].active is True
    assert len(result.models[1].digest or "") == 128
    assert result.models[1].metadata_truncated is True


def test_show_service_exposes_only_allowlisted_bounded_fields() -> None:
    result = ShowModelService(FakeProvider(), "otro").run(
        "modelo",
        timeout_seconds=2,
    )

    assert result.name == "modelo"
    assert result.active is False
    assert len(result.format or "") == 128
    assert result.family == "generic family"
    assert len(result.capabilities) == 20
    assert result.metadata_truncated is True
    assert not hasattr(result, "template")
    assert not hasattr(result, "modelfile")
    assert not hasattr(result, "parameters")


def test_models_list_json_has_stable_allowlist(
    capsys,
) -> None:  # noqa: ANN001
    result = ModelListResult(
        active_model="modelo",
        active_model_installed=True,
        models=(),
    )

    cli._render_models_list(result, "json")

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "active_model",
        "active_model_installed",
        "models",
    }


def test_model_show_json_has_no_raw_ollama_fields(capsys) -> None:  # noqa: ANN001
    result = ModelDetailsView(
        name="modelo",
        active=True,
        format="gguf",
        family=None,
        parameter_size=None,
        quantization_level=None,
        capabilities=("completion",),
    )

    cli._render_model_details(result, "json")

    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {
        "name",
        "active",
        "format",
        "family",
        "parameter_size",
        "quantization_level",
        "capabilities",
        "metadata_truncated",
    }
    assert "template" not in payload
    assert "modelfile" not in payload
    assert "parameters" not in payload
