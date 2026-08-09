from __future__ import annotations

import json
from pathlib import Path

from barbarion.domain.technical_patterns import PatternResultStatus, detect_patterns
from tests.unit.test_h42_patterns import _relation, _symbol


FIXTURE = Path(__file__).parents[1] / "fixtures" / "h42_pattern_benchmark.json"


def _case_graph(names: list[str], edges: list[list[str]]):
    symbols = {name: _symbol(name, index + 1) for index, name in enumerate(names)}
    relations = tuple(
        _relation(f"{source}-{target}-{index}", symbols[source], symbols[target], index + 1)
        for index, (source, target) in enumerate(edges)
    )
    return tuple(symbols.values()), relations


def test_h42_benchmark_is_public_and_deterministic() -> None:
    dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert dataset["public"] is True
    assert dataset["threshold_decision"] == "pending_baseline"
    observations: list[tuple[str, int | str]] = []
    for case in dataset["cases"]:
        symbols, relations = _case_graph(case["nodes"], case["edges"])
        result = next(
            item
            for item in detect_patterns(
                symbols,
                relations,
                pattern_types=frozenset({case["pattern"]}),
            )
            if item.subject_symbol_id == _symbol(case["subject"], 1).symbol_id
        )
        expected = case["expected"]
        if "status" in expected:
            assert result.status is PatternResultStatus.INSUFFICIENT_EVIDENCE
        elif case["pattern"] == "component_reuse":
            value = result.metrics_primary["distinct_source_symbols"]
            assert value == expected["distinct_source_symbols"]
            observations.append((case["id"], value))
        else:
            value = result.metrics_primary["distinct_total_neighbors"]
            assert value == expected["distinct_total_neighbors"]
            observations.append((case["id"], value))

        repeated = detect_patterns(
            symbols,
            relations,
            pattern_types=frozenset({case["pattern"]}),
        )
        assert result.result_fingerprint == next(
            item.result_fingerprint
            for item in repeated
            if item.subject_symbol_id == result.subject_symbol_id
        )

    # El benchmark observa separación sintética, pero no convierte la separación
    # en threshold de producción.
    assert dict(observations)["reuse_multiple_sources"] > dict(observations)["reuse_repeated_same_source"]
    assert dict(observations)["centrality_multiple_neighbors"] > dict(observations)["centrality_cycle"]
