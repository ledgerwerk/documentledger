from __future__ import annotations

from pathlib import Path


def test_skill_mentions_canonical_documentation_workflow() -> None:
    text = Path("skills/documentledger/SKILL.md").read_text(encoding="utf-8")
    assert "documentledger --json status" in text
    assert "documentledger --json scan" in text
    assert "documentledger --json document affected" in text
    assert "documentledger document build-context" in text
    assert "Do not edit `.ledger/`" in text
    assert "validation before `mark-fresh`" in text or "Never mark fresh after a failed or skipped required build" in text
