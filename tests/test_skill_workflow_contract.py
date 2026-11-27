from __future__ import annotations

from pathlib import Path

from tests.test_skill_files import _skill_invocations

SKILL_PATH = Path("skills/documentledger/SKILL.md")
QUICKSTART_PATH = Path("docs/quickstart.md")
BOOTSTRAP_PATH = Path("docs/bootstrap.md")


def _invocations_requiring(text: str, fragment: str) -> list[tuple[str, tuple[str, ...] | None]]:
    return [(command, required) for command, required in _skill_invocations(text) if fragment in command]


def test_skill_gates_review_finish_proposals_pagination_and_validation() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    invocations = _skill_invocations(text)

    assert invocations[0][0] == "documentledger --json capabilities"
    assert _invocations_requiring(text, "documentledger review") == [("documentledger review", ("review.v1",))]
    assert _invocations_requiring(text, "documentledger finish") == [("documentledger finish", ("finish.v1",))]
    assert _invocations_requiring(text, "documentledger document validate") == [("documentledger document validate", ("validation.v1",))]

    paginated = [(command, required) for command, required in invocations if "--cursor" in command or "--page-size" in command]
    assert paginated
    assert all(required == ("context_pagination.v1",) for _, required in paginated)

    directory_imports = [
        (command, required) for command, required in invocations if "link import-map" in command and "--directory" in command
    ]
    assert len(directory_imports) == 2
    assert all(required == ("proposal_manifest.v1", "import_map_review.v1") for _, required in directory_imports)
    assert "--review" in directory_imports[0][0]
    assert "--check-and-apply" in directory_imports[1][0]
    assert "If either capability is absent, do not use the directory review path." in text
    assert "stop and request an upgrade rather than bypassing review" in text
    assert "top-level `ok: true`" in text
    assert "python -m sphinx -b html -n -W --keep-going docs docs/_build/html" in text
    assert "configured navigation targets" in text
    assert "releaseledger-owned changelog bytes" in text


def test_quickstart_gates_optional_workflows_and_begins_with_capabilities() -> None:
    text = QUICKSTART_PATH.read_text(encoding="utf-8")
    invocations = _skill_invocations(text)

    assert invocations[0][0] == "documentledger --json capabilities"
    assert any(command == "documentledger finish" and required == ("finish.v1",) for command, required in invocations)
    assert any(command == "documentledger document validate" and required == ("validation.v1",) for command, required in invocations)
    assert any("link import-map" in command and "--review" in command for command, _ in invocations)
    assert all(
        required == ("proposal_manifest.v1", "import_map_review.v1")
        for command, required in invocations
        if "link import-map" in command and "--directory" in command
    )
    assert all(
        required == ("context_pagination.v1",) for command, required in invocations if "--cursor" in command or "--page-size" in command
    )
    assert "Do not use directory imports when either capability is absent." in text


def test_bootstrap_guide_uses_reviewed_manifest_imports() -> None:
    text = BOOTSTRAP_PATH.read_text(encoding="utf-8")
    invocations = _skill_invocations(text)
    directory_imports = [
        (command, required) for command, required in invocations if "link import-map" in command and "--directory" in command
    ]

    assert invocations[0][0] == "documentledger --json capabilities"
    assert len(directory_imports) == 2
    assert all(required == ("proposal_manifest.v1", "import_map_review.v1") for _, required in directory_imports)
