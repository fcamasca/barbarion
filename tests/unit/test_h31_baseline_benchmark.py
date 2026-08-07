from __future__ import annotations

import json
from pathlib import Path

from tests.support.h31_baseline_benchmark import (
    DEFAULT_DATASET,
    load_dataset,
    run_baseline,
    write_reports,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "h31"


def test_dataset_is_synthetic_publicable_and_covers_required_cases() -> None:
    dataset = load_dataset(ROOT / DEFAULT_DATASET)

    assert dataset["license"] == "synthetic-for-barbarion"
    assert len(dataset["cases"]) >= 10
    assert {
        "literal",
        "semantic",
        "multi_source",
        "overlap",
        "duplicate",
        "retrieval_limit",
        "ambiguity",
        "insufficient",
        "structured",
        "repair",
    } <= {case["category"] for case in dataset["cases"]}


def test_baseline_is_deterministic_and_does_not_enable_optimization() -> None:
    dataset = load_dataset(ROOT / DEFAULT_DATASET)

    first = run_baseline(dataset)
    second = run_baseline(dataset)

    assert first == second
    assert first["optimization_enabled"] is False
    assert first["policy"] == "baseline_v1"
    assert first["estimator_id"] == "chars4_v1"
    assert first["decisions"]["token_reduction_target"] is None
    assert first["decisions"]["t04_t08_gate"] == "pending-human-review"


def test_baseline_measures_retrieval_coverage_and_insufficient_behavior() -> None:
    result = run_baseline(load_dataset(ROOT / DEFAULT_DATASET))
    cases = {case["id"]: case for case in result["cases"]}

    assert result["metrics"]["recall_at_5"] == 0.888889
    assert result["metrics"]["recall_at_10"] == 1.0
    assert result["metrics"]["mrr"] == 0.851852
    assert cases["relevant-at-six"]["recall_at_5"] == 0.0
    assert cases["relevant-at-six"]["recall_at_10"] == 1.0
    assert cases["relevant-at-six"]["selected_source_recall"] == 0.0
    assert cases["relevant-at-six"]["fact_coverage"] == 0.0
    assert cases["relevant-at-six"]["citation_recall"] == 0.0
    assert cases["relevant-at-six"]["result_status"] == "insufficient"
    assert cases["insufficient-empty"]["generation"] is None
    assert cases["insufficient-empty"]["result_status"] == "insufficient"


def test_baseline_measures_prompt_components_redundancy_and_repair() -> None:
    result = run_baseline(load_dataset(ROOT / DEFAULT_DATASET))
    metrics = result["metrics"]
    cases = {case["id"]: case for case in result["cases"]}

    assert metrics["exact_duplicate_pairs"] == 1
    assert metrics["overlap_pairs"] == 1
    assert metrics["overlap_chars"] == 27
    assert result["generation_components"]["source_metadata"]["tokens_est_local"] > 0
    assert result["generation_components"]["source_content"]["tokens_est_local"] > 0
    assert metrics["generation_prompt_tokens_est_local_total"] == 2523
    assert metrics["repair_prompt_count"] == 1
    assert metrics["repair_prompt_tokens_est_local_total"] == 154
    assert cases["citation-repair"]["repair"] is not None
    literal_decisions = cases["literal-single"]["evidence_decisions"]
    assert {decision["citation_status"] for decision in literal_decisions} == {
        "cited",
        "not_cited",
    }
    assert all(
        case["generation"] is None
        or (
            case["generation"]["chars_reconciled"]
            and case["generation"]["utf8_bytes_reconciled"]
        )
        for case in result["cases"]
    )


def test_committed_reports_are_exactly_reproducible(tmp_path: Path) -> None:
    result = run_baseline(load_dataset(ROOT / DEFAULT_DATASET))
    write_reports(result, tmp_path)

    for name in (
        "t03-baseline.json",
        "t03-baseline.md",
        "t04-redundancy-report.json",
        "t04-redundancy-report.md",
    ):
        assert (tmp_path / name).read_bytes() == (REPORT_DIR / name).read_bytes()


def test_versioned_artifacts_do_not_contain_private_path_or_secret_canaries() -> None:
    paths = (
        ROOT / DEFAULT_DATASET,
        REPORT_DIR / "t03-baseline.json",
        REPORT_DIR / "t03-baseline.md",
    )
    forbidden = (
        "C:\\Users\\",
        "D:\\",
        "sk-ant-",
        "api_key",
        "password",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert all(canary not in text for canary in forbidden)
        if path.suffix == ".json":
            json.loads(text)
