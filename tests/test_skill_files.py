from __future__ import annotations

from pathlib import Path


def test_skill_mentions_required_workflow() -> None:
    text = Path("skills/documentledger/SKILL.md").read_text(encoding="utf-8")
    assert "docledger --json status" in text
    assert "docledger --json scan" in text
    assert "docledger docs build-context" in text
    assert "Do not edit `.documentledger/` directly" in text
    assert "validation before `mark-fresh`" in text
    assert "Inspect every linked source file" in text
