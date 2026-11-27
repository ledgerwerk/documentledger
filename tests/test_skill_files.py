from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from documentledger.capabilities import capability_record
from documentledger.command_catalog import COMMAND_INVENTORY
from documentledger.proposal_manifest import PROPOSAL_MANIFEST_SCHEMA
from tests.conftest import invoke_json

SKILL_PATH = Path("skills/documentledger/SKILL.md")


def _skill_invocations(text: str) -> list[tuple[str, tuple[str, ...] | None]]:
    invocations: list[tuple[int, str, tuple[str, ...] | None]] = []
    masked = list(text)
    gated_blocks = re.compile(
        r"(?m)(?:<!--\s*requires-capability:\s*([\w.-]+(?:\s*,\s*[\w.-]+)*)\s*-->\s*\n)?```bash[^\n]*\n(.*?)\n```",
        flags=re.DOTALL,
    )
    for match in gated_blocks.finditer(text):
        required = tuple(part.strip() for part in match.group(1).split(",")) if match.group(1) else None
        position = match.start(2)
        pending = ""
        pending_position = position
        for raw_line in match.group(2).splitlines(keepends=True):
            line = raw_line.strip().removeprefix("$ ")
            if not pending:
                pending_position = position
            if line.endswith("\\"):
                pending += line[:-1].rstrip() + " "
            else:
                command = (pending + line).strip()
                if command.startswith("documentledger "):
                    invocations.append((pending_position, command, required))
                pending = ""
            position += len(raw_line)
        masked[match.start() : match.end()] = " " * (match.end() - match.start())
    masked_text = "".join(masked)
    for match in re.finditer(r"`([^`\n]+)`", masked_text):
        command = match.group(1).strip()
        if command.startswith("documentledger "):
            invocations.append((match.start(1), command, None))
    return [(command, required) for _, command, required in sorted(invocations, key=lambda item: item[0])]


def _option_names(command: Any) -> set[str]:
    return {
        option for parameter in command.params for option in (*getattr(parameter, "opts", []), *getattr(parameter, "secondary_opts", []))
    }


def _resolve_cli_command(root: Any, command_path: str) -> Any:
    command = root
    for part in command_path.split():
        command = command.get_command(None, part)
        assert command is not None, f"CLI command is not registered: {command_path}"
    return command


def _validate_invocation(invocation: str, root: Any, command_paths: set[str], root_options: set[str]) -> None:
    tokens = shlex.split(invocation)
    assert tokens and tokens[0] == "documentledger", invocation
    tokens = tokens[1:]
    while tokens and tokens[0].startswith("--") and tokens[0].split("=", 1)[0] in root_options:
        option = tokens.pop(0).split("=", 1)[0]
        if option == "--root" and tokens and not tokens[0].startswith("-"):
            tokens.pop(0)
    path = next(
        (" ".join(tokens[:size]) for size in range(len(tokens), 0, -1) if " ".join(tokens[:size]) in command_paths),
        None,
    )
    assert path is not None, f"Skill references an unsupported command: {invocation}"
    command = _resolve_cli_command(root, path)
    allowed_options = root_options | _option_names(command)
    for token in tokens[len(path.split()) :]:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            assert option in allowed_options, f"Skill references unsupported option {option}: {invocation}"


def test_skill_starts_with_capability_handshake() -> None:
    invocations = _skill_invocations(SKILL_PATH.read_text(encoding="utf-8"))
    assert invocations[0][0] == "documentledger --json capabilities"


def test_capability_contract_matches_package_and_command_catalog(runner) -> None:
    result = invoke_json(runner, ["capabilities"])["result"]
    catalog_paths = sorted(entry.path for entry in COMMAND_INVENTORY.entries)

    assert result["schema"] == "documentledger.capabilities.v1"
    from documentledger import __version__
    from documentledger.storage import STORAGE_SCHEMA_VERSION

    assert set(result) == {"schema", "version", "storage_schema", "features", "capabilities", "commands"}
    assert result["version"] == __version__
    assert result["storage_schema"] == STORAGE_SCHEMA_VERSION
    assert result["storage_schema"] > 0
    assert result["commands"] == catalog_paths
    assert result["features"]["review"] is ("review" in catalog_paths)
    assert result["features"]["finish"] is ("finish" in catalog_paths and "document validate" in catalog_paths)
    assert result["features"]["proposal_manifest"] is (
        PROPOSAL_MANIFEST_SCHEMA == "documentledger.proposal_manifest.v1"
        and "link propose" in catalog_paths
        and "link import-map" in catalog_paths
    )
    assert result["features"]["context_pagination"] is True
    assert result["features"]["import_map_review"] is True
    assert result["features"]["validation"] is ("document validate" in catalog_paths)
    expected_capabilities = [
        capability
        for capability, enabled in (
            ("review.v1", result["features"]["review"]),
            ("finish.v1", result["features"]["finish"]),
            ("proposal_manifest.v1", result["features"]["proposal_manifest"]),
            ("context_pagination.v1", result["features"]["context_pagination"]),
            ("import_map_review.v1", result["features"]["import_map_review"]),
            ("validation.v1", result["features"]["validation"]),
        )
        if enabled
    ]
    assert result["capabilities"] == sorted(expected_capabilities)


def test_skill_commands_and_options_exist_or_are_capability_gated() -> None:
    from typer.main import get_command

    from documentledger.cli import app

    workflow_texts = [
        SKILL_PATH.read_text(encoding="utf-8"),
        Path("docs/quickstart.md").read_text(encoding="utf-8"),
        Path("docs/bootstrap.md").read_text(encoding="utf-8"),
    ]
    root = get_command(app)
    command_paths = {entry.path for entry in COMMAND_INVENTORY.entries}
    root_options = _option_names(root)
    supported_capabilities = set(capability_record()["capabilities"])

    for workflow_text in workflow_texts:
        for invocation, required_capabilities in _skill_invocations(workflow_text):
            if required_capabilities is not None and not set(required_capabilities) <= supported_capabilities:
                continue
            _validate_invocation(invocation, root, command_paths, root_options)
