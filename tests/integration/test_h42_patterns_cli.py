from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import barbarion.cli as cli
from barbarion.database import initialize_database
from tests.unit.test_h42_patterns import _relation, _symbol


def _run_patterns(
    monkeypatch,
    tmp_path: Path,
    *,
    debug: bool,
    llm_called: list[bool],
    preflight_called: list[bool],
) -> tuple[str, str]:
    source, target = _symbol("SENSITIVE_SOURCE", 1), _symbol("SENSITIVE_TARGET", 2)
    relation = _relation("sensitive-call", source, target, 1)
    database_path = tmp_path / "patterns.db"
    database_path.touch()
    initialize_database(database_path)

    class FakeRepository:
        def __init__(self, path):
            assert path == database_path

        def active_symbols(self):
            return (source, target)

        def active_relations(self):
            return (relation,)

    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda _config: SimpleNamespace(database_path=database_path),
    )
    monkeypatch.setattr(cli, "initialize_database", lambda _path: None)
    monkeypatch.setattr(cli, "SQLiteReverseEngineeringRepository", FakeRepository)
    monkeypatch.setattr(
        cli,
        "_build_llm_provider",
        lambda _settings: llm_called.append(True),
    )
    monkeypatch.setattr(
        cli,
        "_build_privacy_preflight",
        lambda _settings: preflight_called.append(True),
    )

    args = SimpleNamespace(
        config=None,
        pattern_types=["component_reuse"],
        format="json",
        debug=debug,
    )
    exit_code = cli._run_patterns(args)
    assert exit_code == 0
    captured = cli.sys.stdout.getvalue() if hasattr(cli.sys.stdout, "getvalue") else None
    return captured or "", ""


def test_patterns_debug_is_safe_and_reports_descriptive_metrics(
    monkeypatch, tmp_path, capsys
) -> None:
    llm_called: list[bool] = []
    preflight_called: list[bool] = []

    cli._run_patterns(
        SimpleNamespace(
            config=None,
            pattern_types=["component_reuse"],
            format="json",
            debug=True,
        )
    ) if False else None

    source, target = _symbol("SENSITIVE_SOURCE", 1), _symbol("SENSITIVE_TARGET", 2)
    relation = _relation("sensitive-call", source, target, 1)
    database_path = tmp_path / "patterns.db"
    database_path.touch()
    initialize_database(database_path)

    class FakeRepository:
        def __init__(self, _path):
            pass

        def active_symbols(self):
            return (source, target)

        def active_relations(self):
            return (relation,)

    monkeypatch.setattr(cli, "load_settings", lambda _config: SimpleNamespace(database_path=database_path))
    monkeypatch.setattr(cli, "initialize_database", lambda _path: None)
    monkeypatch.setattr(cli, "SQLiteReverseEngineeringRepository", FakeRepository)
    monkeypatch.setattr(cli, "_build_llm_provider", lambda _settings: llm_called.append(True))
    monkeypatch.setattr(cli, "_build_privacy_preflight", lambda _settings: preflight_called.append(True))

    args = SimpleNamespace(config=None, pattern_types=["component_reuse"], format="json", debug=True)
    assert cli._run_patterns(args) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    debug = captured.err
    assert "patterns_started=1" in debug
    assert "patterns_finished=1" in debug
    assert "subjects_evaluated=2" in debug
    assert "relations_considered=1" in debug
    assert "patterns_not_evaluated=1" in debug
    assert "insufficient_evidence=1" in debug
    assert "patterns_detected=0" in debug
    assert "policy_id=descriptive_v1" in debug
    assert "duration_ms=" in debug
    assert "SENSITIVE_SOURCE" not in debug
    assert "SENSITIVE_TARGET" not in debug
    assert {item["status"] for item in payload["patterns"]} == {
        "not_evaluated",
        "insufficient_evidence",
    }
    assert llm_called == []
    assert preflight_called == []

    if database_path.exists():
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM rag_queries").fetchone()[0] == 0


def test_patterns_debug_does_not_change_functional_json(monkeypatch, tmp_path, capsys) -> None:
    source, target = _symbol("SOURCE", 1), _symbol("TARGET", 2)
    relation = _relation("call", source, target, 1)
    database_path = tmp_path / "patterns.db"
    database_path.touch()

    class FakeRepository:
        def __init__(self, _path):
            pass

        def active_symbols(self):
            return (source, target)

        def active_relations(self):
            return (relation,)

    monkeypatch.setattr(cli, "load_settings", lambda _config: SimpleNamespace(database_path=database_path))
    monkeypatch.setattr(cli, "initialize_database", lambda _path: None)
    monkeypatch.setattr(cli, "SQLiteReverseEngineeringRepository", FakeRepository)
    args = SimpleNamespace(config=None, pattern_types=["component_reuse"], format="json", debug=False)
    assert cli._run_patterns(args) == 0
    first = capsys.readouterr()
    args.debug = True
    assert cli._run_patterns(args) == 0
    second = capsys.readouterr()
    assert json.loads(first.out) == json.loads(second.out)
