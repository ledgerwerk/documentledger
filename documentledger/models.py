from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    root: Path
    path: Path
    project_name: str
    project_uuid: str
    storage_dir: Path
    source_roots: list[str]
    doc_roots: list[str]
    source_extensions: list[str]
    doc_extensions: list[str]
    validation_commands: list[str]
    require_doc_frontmatter: bool = False


@dataclass
class Workspace:
    config: Config
    metadata: dict[str, object]


@dataclass
class ScanResult:
    scan_id: str
    changed_sources: list[str] = field(default_factory=list)
    deleted_sources: list[str] = field(default_factory=list)
    stale_docs: list[str] = field(default_factory=list)
    unlinked_changed_sources: list[str] = field(default_factory=list)
    source_hashes: dict[str, str] = field(default_factory=dict)
    doc_hashes: dict[str, str] = field(default_factory=dict)
