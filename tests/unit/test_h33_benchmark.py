"""Pruebas del benchmark sintético y gate de límites H3.3."""

from tests.support.h33_graph_benchmark import load_dataset, run_benchmark


def test_h33_benchmark_improves_multi_component_coverage_without_simple_regression() -> None:
    result = run_benchmark(load_dataset(), repetitions=1)
    baseline = result["policies"]["baseline"]
    balanced = result["policies"]["balanced"]

    assert baseline["metrics"]["multi_component_recall"] < 0.5
    assert balanced["metrics"]["multi_component_recall"] == 1.0
    assert balanced["metrics"]["simple_recall"] == 1.0
    assert balanced["metrics"]["noise_ratio"] <= 0.15
    assert result["recommendation"]["policy"] == "balanced"


def test_h33_benchmark_evidence_is_provider_independent() -> None:
    result = run_benchmark(load_dataset(), repetitions=1)

    assert all(
        policy["provider_evidence_equal"]
        for policy in result["policies"].values()
    )
