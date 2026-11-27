from __future__ import annotations

from typing import Any

from documentledger import __version__
from documentledger.command_catalog import COMMAND_INVENTORY
from documentledger.proposal_manifest import PROPOSAL_MANIFEST_SCHEMA
from documentledger.storage import STORAGE_SCHEMA_VERSION


def _command_options(command_path: str) -> set[str]:
    from typer.main import get_command

    from documentledger.cli import app

    command: Any = get_command(app)
    for part in command_path.split():
        command = command.get_command(None, part)
        if command is None:
            return set()
    return {
        option for parameter in command.params for option in (*getattr(parameter, "opts", []), *getattr(parameter, "secondary_opts", []))
    }


def capability_record() -> dict[str, Any]:
    command_paths = sorted(entry.path for entry in COMMAND_INVENTORY.entries)
    command_path_set = set(command_paths)
    validation = "document validate" in command_path_set
    features = {
        "review": "review" in command_path_set,
        "finish": "finish" in command_path_set and validation,
        "proposal_manifest": PROPOSAL_MANIFEST_SCHEMA == "documentledger.proposal_manifest.v1"
        and "link propose" in command_path_set
        and "link import-map" in command_path_set,
        "context_pagination": {"--cursor", "--page-size"} <= _command_options("document build-context"),
        "import_map_review": "--review" in _command_options("link import-map"),
        "validation": validation,
    }
    capabilities = sorted(f"{name}.v1" for name, enabled in features.items() if enabled)
    return {
        "schema": "documentledger.capabilities.v1",
        "version": __version__,
        "storage_schema": STORAGE_SCHEMA_VERSION,
        "features": features,
        "capabilities": capabilities,
        "commands": command_paths,
    }
