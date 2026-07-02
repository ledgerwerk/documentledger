from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True)
class SourceUnit:
    source_id: str
    path: str
    kind: str
    qualname: str
    line_span: tuple[int, int]
    signature: str
    hashes: dict[str, str]

    def to_record(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "path": self.path,
            "kind": self.kind,
            "qualname": self.qualname,
            "line_span": [self.line_span[0], self.line_span[1]],
            "signature": self.signature,
            "hashes": dict(self.hashes),
        }


@dataclass(frozen=True)
class DocSection:
    section_id: str
    doc_path: str
    heading_path: list[str]
    heading_slug: str
    line_span: tuple[int, int]
    section_hash: str
    summary: str
    text: str

    def to_record(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "doc_path": self.doc_path,
            "heading_path": list(self.heading_path),
            "heading_slug": self.heading_slug,
            "line_span": [self.line_span[0], self.line_span[1]],
            "section_hash": self.section_hash,
            "summary": self.summary,
        }


@dataclass
class ScanResult:
    version: int
    changed_sources: list[str] = field(default_factory=list)
    deleted_sources: list[str] = field(default_factory=list)
    stale_docs: list[str] = field(default_factory=list)
    unlinked_changed_sources: list[str] = field(default_factory=list)
    changed_units: list[dict[str, Any]] = field(default_factory=list)
    added_units: list[dict[str, Any]] = field(default_factory=list)
    deleted_units: list[dict[str, Any]] = field(default_factory=list)
    affected_sections: list[dict[str, Any]] = field(default_factory=list)
    unmapped_changed_units: list[dict[str, Any]] = field(default_factory=list)
    source_units: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_hashes: dict[str, str] = field(default_factory=dict)
    doc_hashes: dict[str, str] = field(default_factory=dict)
    unchanged: bool = False
