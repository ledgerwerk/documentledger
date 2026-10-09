from __future__ import annotations

from pathlib import Path


def test_skill_enforces_full_documentation_bootstrap_contract() -> None:
    text = Path("skills/documentledger/SKILL.md").read_text(encoding="utf-8")

    assert "documentledger --json status" in text
    assert "documentledger --json doctor" in text
    assert "require `result.ok`" in text
    assert "documentledger --json scan" in text
    assert "--out -" in text
    assert "truncated" in text and "omitted" in text and "next_cursor" in text
    assert "--cursor NEXT_CURSOR" in text and "--strict" in text
    assert "docs/requirements.txt" in text
    assert "docs/index.md" in text
    assert "include `changelog` in navigation" in text
    assert "Preserve releaseledger-owned changelog bytes" in text
    assert "python -m sphinx -b html -n -W --keep-going docs docs/_build/html" in text
    assert "strict documentation-completion gate" in text
    assert "Try a supported output alternative and resume" in text
    assert "the user's requested documentation work" in text
    assert "--allow-unlinked --all` as a default shortcut" in text
    assert "/tmp" not in text

    assert "--directory DIR --review" in text
    assert "--replace-owned-proposals" in text
    assert "scan-bound manifest" in text
    author_phase = text.index("### 4. Author Markdown and Sphinx pages before linking")
    proposal_phase = text.index("### 5. Reconcile headings and review mapping proposals")
    validation_phase = text.index("### 6. Validate the actual current docs")
    final_phase = text.index("### 7. Freshness, completion gate, and final response")
    assert author_phase < proposal_phase < validation_phase < final_phase
