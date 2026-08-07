from __future__ import annotations

import json
from pathlib import Path

from barbarion.config import load_settings


ROOT = Path(__file__).resolve().parents[2]


def test_t10_gate_matches_benchmark_and_does_not_promote_default(tmp_path: Path) -> None:
    t07 = json.loads(
        (ROOT / "reports/h31/t07-relevance-first.json").read_text(encoding="utf-8")
    )
    t10 = json.loads(
        (ROOT / "reports/h31/t10-regression.json").read_text(encoding="utf-8")
    )
    settings = load_settings(environ={}, cwd=tmp_path)

    assert t07["quality_gate"] == {
        "key_case_recovered": True,
        "no_retrieval_or_citation_regression": True,
    }
    assert t10["benchmark"]["optimized_fact_coverage"] == 1.0
    assert t10["benchmark"]["no_retrieval_or_citation_regression"] is True
    assert t10["default_decision"]["optimized_v1_status"] == "qualified_candidate"
    assert t10["default_decision"]["promoted"] is False
    assert settings.rag.context_selection_policy == "baseline_v1"
