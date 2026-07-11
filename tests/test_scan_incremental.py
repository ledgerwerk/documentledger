from __future__ import annotations

from pathlib import Path

import documentledger.scanner as scanner
from tests.conftest import invoke_json, load_json, load_yaml


def test_unchanged_scan_skips_reindex(monkeypatch, project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    calls: list[tuple[str, list[str]]] = []
    original_inventory = scanner.source_inventory
    original_selected = scanner.source_inventory_for_paths

    def counted_inventory(root: Path, source_paths: list[str]):
        calls.append(("full", list(source_paths)))
        return original_inventory(root, source_paths)

    def counted_selected(root: Path, source_paths):
        calls.append(("selected", list(source_paths)))
        return original_selected(root, source_paths)

    monkeypatch.setattr(scanner, "source_inventory", counted_inventory)
    monkeypatch.setattr(scanner, "source_inventory_for_paths", counted_selected)
    data = invoke_json(runner, ["scan"])["result"]
    assert data["unchanged"] is True
    assert calls == []


def test_doc_only_scan_skips_source_reindex(monkeypatch, project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "README.md").write_text("# changed docs\n", encoding="utf-8")
    calls: list[tuple[str, list[str]]] = []
    original_inventory = scanner.source_inventory
    original_selected = scanner.source_inventory_for_paths

    def counted_inventory(root: Path, source_paths: list[str]):
        calls.append(("full", list(source_paths)))
        return original_inventory(root, source_paths)

    def counted_selected(root: Path, source_paths):
        calls.append(("selected", list(source_paths)))
        return original_selected(root, source_paths)

    monkeypatch.setattr(scanner, "source_inventory", counted_inventory)
    monkeypatch.setattr(scanner, "source_inventory_for_paths", counted_selected)
    data = invoke_json(runner, ["scan"])["result"]
    assert data["changed_sources"] == []
    assert calls == []


def test_changed_source_scan_reindexes_only_changed_path(monkeypatch, project: Path, runner) -> None:
    invoke_json(runner, ["init"])
    invoke_json(runner, ["scan"])
    (project / "documentledger" / "cli.py").write_text("print('changed')\n", encoding="utf-8")
    calls: list[list[str]] = []
    original_selected = scanner.source_inventory_for_paths

    def counted_selected(root: Path, source_paths):
        calls.append(list(source_paths))
        return original_selected(root, source_paths)

    monkeypatch.setattr(scanner, "source_inventory_for_paths", counted_selected)
    data = invoke_json(runner, ["scan"])["result"]
    assert data["changed_sources"] == ["documentledger/cli.py"]
    assert calls == [["documentledger/cli.py"]]
    assert "source_units" not in load_yaml(project / ".documentledger" / "scan.yaml")
    assert load_json(project / ".documentledger" / "source-index.json")["source_units"]
