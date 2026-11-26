from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


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
    mapping_review_roles: list[str] = field(default_factory=lambda: ["production"])


LayoutSource = Literal["canonical", "legacy"]


@dataclass(frozen=True, slots=True)
class ToolConfig:
    """Documentledger's tool-owned schema-2 configuration.

    Project identity and storage routing deliberately do not live here. They
    are supplied by the shared ledgercore manifest and resolved layout.
    """

    config_version: int
    ledger_code: str
    source_roots: tuple[str, ...]
    doc_roots: tuple[str, ...]
    source_extensions: tuple[str, ...]
    doc_extensions: tuple[str, ...]
    validation_commands: tuple[str, ...]
    mapping_review_roles: tuple[str, ...] = ("production",)
    require_doc_frontmatter: bool = False


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """Resolved canonical or legacy paths, kept separate from tool config."""

    project_root: Path
    manifest_path: Path | None
    local_config_path: Path | None
    config_path: Path
    data_dir: Path
    artifacts_dir: Path | None
    config_binding_path: Path | None
    data_binding_path: Path | None
    artifacts_binding_path: Path | None
    layout_source: LayoutSource

    @property
    def storage_dir(self) -> Path:
        """Compatibility alias for storage call sites during the migration."""
        return self.data_dir


@dataclass
class Workspace:
    config: Config
    metadata: dict[str, object]
    paths: WorkspacePaths | None = None
    project_name: str | None = None
    project_uuid: str | None = None

    source_root_discovery: dict[str, object] | None = None


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
    body_hash: str
    body_length: int
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
            "body_hash": self.body_hash,
            "body_length": self.body_length,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class ChangedEvidence:
    source_id: str
    source_path: str
    changed_hashes: tuple[str, ...]
    role: str

    def to_record(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_path": self.source_path,
            "changed_hashes": list(self.changed_hashes),
            "role": self.role,
        }


@dataclass(frozen=True)
class ReviewItem:
    doc_path: str
    section_id: str
    section_title: str
    action: Literal["update_required", "review_required", "generated_verify"]
    severity: Literal["high", "medium", "low"]
    evidence: tuple[ChangedEvidence, ...]
    reasons: tuple[str, ...]

    def to_record(self, *, limit: int | None = 40) -> dict[str, Any]:
        evidence = list(self.evidence)
        changed_units = evidence if limit is None else evidence[:limit]
        return {
            "doc": self.doc_path,
            "section_id": self.section_id,
            "title": self.section_title,
            "action": self.action,
            "severity": self.severity,
            "changed_units": [item.to_record() for item in changed_units],
            "changed_units_total": len(evidence),
            "changed_units_omitted": max(len(evidence) - len(changed_units), 0),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MappingSuggestion:
    doc_path: str
    section_id: str
    source_id: str
    confidence: str
    coverage: str
    impact: str
    reason: str
    evidence_text: str
    auto_applied: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "doc": self.doc_path,
            "section_id": self.section_id,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "coverage": self.coverage,
            "impact": self.impact,
            "reason": self.reason,
            "evidence": self.evidence_text[:200],
            "evidence_truncated": len(self.evidence_text) > 200,
            "auto_applied": self.auto_applied,
        }


@dataclass(frozen=True)
class AmbiguousMatch:
    doc_path: str
    section_id: str
    evidence_text: str
    span: tuple[int, int]

    def to_record(self) -> dict[str, Any]:
        return {
            "doc": self.doc_path,
            "section_id": self.section_id,
            "evidence": self.evidence_text[:200],
            "evidence_truncated": len(self.evidence_text) > 200,
            "span": list(self.span),
        }


@dataclass(frozen=True)
class ReviewPlan:
    scan_version: int
    state: str
    affected: tuple[ReviewItem, ...]
    unmapped_relevant: tuple[ChangedEvidence, ...]
    mapping_suggestions: tuple[MappingSuggestion, ...]
    auto_applied: tuple[MappingSuggestion, ...]
    ambiguous_items: tuple[AmbiguousMatch, ...]
    ambiguous_match_count: int
    ignored_change_counts: dict[str, int]
    next_action: dict[str, str]

    def to_record(self, *, details: bool = False, limit: int = 40) -> dict[str, Any]:
        cap = None if details else limit
        affected = list(self.affected)
        unmapped = list(self.unmapped_relevant)
        suggestions = list(self.mapping_suggestions)
        applied = list(self.auto_applied)
        ambiguous = list(self.ambiguous_items)
        pending_count = len(self.unmapped_relevant) + len(self.mapping_suggestions) + self.ambiguous_match_count
        return {
            "schema": "documentledger.review.v1",
            "state": self.state,
            "scan_version": self.scan_version,
            "affected": [item.to_record(limit=cap) for item in affected[:cap]],
            "affected_total": len(affected),
            "unmapped_relevant": [item.to_record() for item in unmapped[:cap]],
            "unmapped_relevant_total": len(unmapped),
            "mapping": {
                "auto_applied": len(applied),
                "auto_applied_edges": [item.to_record() for item in applied[:cap]],
                "review_required": pending_count,
                "suggestions": [item.to_record() for item in suggestions[:cap]],
                "ambiguous_matches": self.ambiguous_match_count,
                "ambiguous_items": [item.to_record() for item in ambiguous[:cap]],
            },
            "ignored_changes": dict(self.ignored_change_counts),
            "next_action": dict(self.next_action),
            "omitted": {
                "affected": max(len(affected) - len(affected[:cap]), 0) if cap is not None else 0,
                "unmapped_relevant": max(len(unmapped) - len(unmapped[:cap]), 0) if cap is not None else 0,
                "suggestions": max(len(suggestions) - len(suggestions[:cap]), 0) if cap is not None else 0,
                "auto_applied_edges": max(len(applied) - len(applied[:cap]), 0) if cap is not None else 0,
                "ambiguous_items": max(len(ambiguous) - len(ambiguous[:cap]), 0) if cap is not None else 0,
            },
        }


FreshnessDisposition = Literal["updated", "reviewed-no-change", "generated-verified"]
ReviewDecisionDisposition = Literal["reviewed-no-change", "generated-verified"]


@dataclass(frozen=True)
class ReviewDecision:
    doc_path: str
    section_id: str
    disposition: ReviewDecisionDisposition
    reason: str


@dataclass(frozen=True)
class FreshnessResolution:
    doc_path: str
    section_id: str
    disposition: FreshnessDisposition
    reason: str
    scan_version: int
    section_hash: str

    def to_record(self) -> dict[str, Any]:
        return {
            "doc": self.doc_path,
            "section_id": self.section_id,
            "disposition": self.disposition,
            "reason": self.reason,
            "source_scan_version": self.scan_version,
            "section_hash": self.section_hash,
        }


@dataclass(frozen=True)
class ValidationResult:
    command: str
    exit_code: int
    output: str
    output_truncated: bool = False

    def to_record(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "passed": self.exit_code == 0,
            "output": self.output,
            "output_truncated": self.output_truncated,
        }


@dataclass(frozen=True)
class FinishResult:
    scan_version: int
    resolutions: tuple[FreshnessResolution, ...]
    validation: tuple[ValidationResult, ...]
    audit_ok: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": "documentledger.finish.v1",
            "state": "clean",
            "scan_version": self.scan_version,
            "freshness": [item.to_record() for item in self.resolutions],
            "audit": {"ok": self.audit_ok},
            "validation": [item.to_record() for item in self.validation],
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
    reconciliation: dict[str, Any] = field(default_factory=dict)
    unchanged: bool = False
