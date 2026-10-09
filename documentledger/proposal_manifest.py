"""Scan-bound proposal manifests and reviewed import selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgercore.hashing import sha256_text
from ledgercore.ids import slugify_ref
from ledgercore.yamlio import write_yaml as core_write_yaml

from documentledger.errors import DocumentledgerError
from documentledger.identity import normalize_repo_path
from documentledger.models import Workspace
from documentledger.output import write_output_file
from documentledger.scanner import collect_files, file_hash, hash_paths
from documentledger.storage import latest_scan, read_yaml

PROPOSAL_MANIFEST_NAME = "proposal-manifest.yaml"
PROPOSAL_MANIFEST_SCHEMA = "documentledger.proposal_manifest.v1"


def proposal_filename(doc_path: str) -> str:
    """Return a stable, path-derived filename with a collision-resistant suffix."""
    normalized = normalize_repo_path(doc_path)
    slug = slugify_ref(normalized, empty="doc")[:96].rstrip("-") or "doc"
    return f"{slug}-{sha256_text(normalized)[:16]}.yaml"


def require_current_scan(workspace: Workspace) -> dict[str, Any]:
    """Require a baseline scan whose source and documentation hashes are current."""
    scan = latest_scan(workspace)
    if scan is None:
        raise DocumentledgerError(
            "proposal_scan_required",
            "Mapping proposals require a completed Documentledger scan.",
            ["Run `documentledger scan` and retry proposal generation or review."],
        )
    source_paths = collect_files(workspace, list(workspace.config.source_roots), list(workspace.config.source_extensions))
    doc_paths = collect_files(workspace, list(workspace.config.doc_roots), list(workspace.config.doc_extensions))
    sources_current = hash_paths(workspace, source_paths) == dict(scan.get("source_hashes", {}))
    docs_current = hash_paths(workspace, doc_paths) == dict(scan.get("doc_hashes", {}))
    if not sources_current or not docs_current:
        raise DocumentledgerError(
            "proposal_scan_stale",
            "Source or documentation files changed after the latest scan.",
            ["Run `documentledger scan` before generating, reviewing, or importing mapping proposals."],
            details={
                "scan_version": int(scan.get("version", 0)),
                "source_hashes_current": sources_current,
                "doc_hashes_current": docs_current,
            },
        )
    return scan


def existing_owned_filenames(directory: Path) -> set[str]:
    """Read only ownership names from a prior manifest; reject unsafe manifests."""
    manifest_path = directory / PROPOSAL_MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return set()
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise DocumentledgerError(
            "proposal_manifest_conflict",
            f"The proposal manifest target is not a regular file: {manifest_path}.",
            ["Choose a different proposal output directory or remove the conflicting target yourself."],
        )
    payload = read_yaml(manifest_path)
    if str(payload.get("schema") or "") != PROPOSAL_MANIFEST_SCHEMA:
        raise DocumentledgerError(
            "proposal_manifest_conflict",
            f"An unrecognized file occupies the proposal manifest path: {manifest_path}.",
            ["Choose a different proposal output directory; Documentledger will not overwrite an unrecognized file."],
        )
    return _entry_filenames(payload)


def _string_hash_map(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(digest, str) for key, digest in value.items()):
        raise DocumentledgerError("proposal_manifest_invalid", f"Proposal manifest `{field}` must be a string-to-string mapping.")
    return dict(value)


def _entry_filenames(manifest: dict[str, Any]) -> set[str]:
    documents = manifest.get("documents", [])
    if not isinstance(documents, list):
        raise DocumentledgerError("proposal_manifest_invalid", "Proposal manifest `documents` must be a list.")
    filenames: set[str] = set()
    for entry in documents:
        if not isinstance(entry, dict):
            raise DocumentledgerError("proposal_manifest_invalid", "Proposal manifest document entries must be mappings.")
        filename = str(entry.get("filename") or "")
        if (
            not filename
            or Path(filename).name != filename
            or "/" in filename
            or "\\" in filename
            or filename in {".", "..", PROPOSAL_MANIFEST_NAME}
            or not filename.endswith(".yaml")
        ):
            raise DocumentledgerError("proposal_manifest_invalid", f"Unsafe proposal filename in manifest: {filename!r}.")
        if filename in filenames:
            raise DocumentledgerError("proposal_manifest_invalid", f"Duplicate proposal filename in manifest: {filename}.")
        filenames.add(filename)
    return filenames


def _load_manifest(directory: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = directory / PROPOSAL_MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise DocumentledgerError(
            "proposal_manifest_missing",
            f"No regular proposal manifest exists in {directory}.",
            ["Generate proposals with `documentledger link propose --all-docs`, then review the manifest before importing."],
        )
    manifest = read_yaml(manifest_path)
    if str(manifest.get("schema") or "") != PROPOSAL_MANIFEST_SCHEMA:
        raise DocumentledgerError("proposal_manifest_invalid", f"Unsupported proposal manifest schema in {manifest_path}.")
    _entry_filenames(manifest)
    return manifest_path, manifest


def _validate_manifest_snapshot(workspace: Workspace, manifest: dict[str, Any]) -> dict[str, Any]:
    scan = require_current_scan(workspace)
    raw_scan_version = manifest.get("scan_version")
    if isinstance(raw_scan_version, bool) or not isinstance(raw_scan_version, (int, str)):
        raise DocumentledgerError("proposal_manifest_invalid", "Proposal manifest `scan_version` must be an integer.")
    try:
        manifest_scan_version = int(raw_scan_version)
    except (TypeError, ValueError) as exc:
        raise DocumentledgerError("proposal_manifest_invalid", "Proposal manifest `scan_version` must be an integer.") from exc
    manifest_sources = _string_hash_map(manifest.get("source_hashes"), "source_hashes")
    manifest_docs = _string_hash_map(manifest.get("doc_hashes"), "doc_hashes")
    if (
        manifest_scan_version != int(scan.get("version", 0))
        or str(manifest.get("source_index_hash") or "") != str(scan.get("source_index_hash") or "")
        or manifest_sources != dict(scan.get("source_hashes", {}))
        or manifest_docs != dict(scan.get("doc_hashes", {}))
    ):
        raise DocumentledgerError(
            "proposal_manifest_stale",
            "The proposal manifest does not match the current scan snapshot.",
            ["Regenerate proposals from the current scan, review them, and import only the new manifest entries."],
            details={"manifest_scan_version": manifest.get("scan_version"), "current_scan_version": scan.get("version")},
        )
    return scan


def _manifest_entries(workspace: Workspace, directory: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_manifest_snapshot(workspace, manifest)
    raw_entries = manifest.get("documents", [])
    assert isinstance(raw_entries, list)
    entries: list[dict[str, Any]] = []
    current_doc_hashes = dict(manifest.get("doc_hashes", {}))
    current_source_hashes = _string_hash_map(manifest.get("source_hashes"), "source_hashes")
    for raw_entry in raw_entries:
        entry = raw_entry
        doc_path = normalize_repo_path(str(entry.get("doc_path") or ""))
        if doc_path not in current_doc_hashes or str(entry.get("doc_hash") or "") != str(current_doc_hashes[doc_path]):
            raise DocumentledgerError(
                "proposal_manifest_stale",
                f"The proposal manifest has no current document hash for {doc_path}.",
                ["Regenerate proposals from the current scan and review the new manifest."],
            )
        entry_source_hashes = _string_hash_map(entry.get("source_hashes"), "document.source_hashes")
        if any(current_source_hashes.get(path) != digest for path, digest in entry_source_hashes.items()):
            raise DocumentledgerError(
                "proposal_manifest_stale",
                f"The proposal source hashes for {doc_path} do not match the scan snapshot.",
                ["Regenerate proposals from the current scan and review the new manifest."],
            )
        filename = str(entry["filename"])
        proposal_path = directory / filename
        if proposal_path.is_symlink() or not proposal_path.is_file():
            raise DocumentledgerError("proposal_file_missing", f"Manifest proposal file is missing or unsafe: {proposal_path}.")
        entries.append(entry)
    return entries


def _verify_proposal_payload(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    from documentledger.links import load_mapping_payload

    payload = load_mapping_payload(path)
    payload_doc = normalize_repo_path(str(payload.get("doc_path") or ""))
    entry_doc = normalize_repo_path(str(entry.get("doc_path") or ""))
    if payload_doc != entry_doc:
        raise DocumentledgerError(
            "proposal_manifest_document_mismatch",
            f"Proposal file {path.name} names {payload_doc}, but its manifest entry names {entry_doc}.",
        )
    return payload


def _is_artifact_path(workspace: Workspace, path: Path) -> bool:
    artifacts = getattr(getattr(workspace, "paths", None), "artifacts_dir", None)
    if artifacts is None:
        return False
    try:
        path.resolve().relative_to(Path(artifacts).resolve())
    except ValueError:
        return False
    return True


def _write_manifest(path: Path, manifest: dict[str, Any], workspace: Workspace) -> None:
    write_output_file(
        path,
        lambda target: core_write_yaml(target, manifest, sort_keys=False),
        command="link import-map",
        managed_artifact=_is_artifact_path(workspace, path),
    )


def review_proposal_mappings(
    workspace: Workspace,
    *,
    directory: Path | None,
    mapping_paths: list[Path],
) -> dict[str, Any]:
    """Validate selected generated proposals and seal their exact reviewed contents."""
    if directory is None:
        parents = {path.resolve().parent for path in mapping_paths}
        if len(parents) != 1:
            raise DocumentledgerError("invalid_mapping", "Review files from one proposal directory at a time.")
        directory = next(iter(parents))
    directory = directory.resolve()
    if any(path.resolve().parent != directory for path in mapping_paths):
        raise DocumentledgerError("invalid_mapping", "Reviewed proposal files must belong to the selected directory.")
    manifest_path, manifest = _load_manifest(directory)
    entries = _manifest_entries(workspace, directory, manifest)
    selected_names = {path.resolve().name for path in mapping_paths} if mapping_paths else {str(entry["filename"]) for entry in entries}
    entries_by_name = {str(entry["filename"]): entry for entry in entries}
    unknown = sorted(selected_names - set(entries_by_name))
    if unknown:
        raise DocumentledgerError(
            "unowned_mapping_file",
            "Cannot review proposal files not owned by the manifest: " + ", ".join(unknown),
            ["Regenerate the proposal batch or review a standalone mapping with an explicit --file import."],
        )
    selected_entries = [entries_by_name[name] for name in sorted(selected_names)]
    selected_paths = [directory / str(entry["filename"]) for entry in selected_entries]
    for path, entry in zip(selected_paths, selected_entries, strict=True):
        _verify_proposal_payload(path, entry)
    from documentledger.links import prepare_mapping_batch

    prepare_mapping_batch(workspace, selected_paths)
    for path, entry in zip(selected_paths, selected_entries, strict=True):
        entry["reviewed"] = True
        entry["reviewed_hash"] = file_hash(path)
    _write_manifest(manifest_path, manifest, workspace)
    return {
        "reviewed_files": len(selected_paths),
        "reviewed_documents": [str(entry["doc_path"]) for entry in selected_entries],
        "scan_version": int(manifest.get("scan_version", 0)),
        "manifest": str(manifest_path),
    }


def _validate_reviewed_entry(path: Path, entry: dict[str, Any]) -> None:
    if not bool(entry.get("reviewed")):
        raise DocumentledgerError(
            "mapping_review_required",
            f"Proposal {path.name} has not been reviewed.",
            ["Inspect the proposal, then run `documentledger link import-map --directory DIR --review`."],
        )
    expected_hash = str(entry.get("reviewed_hash") or "")
    if not expected_hash or file_hash(path) != expected_hash:
        raise DocumentledgerError(
            "proposal_changed_after_review",
            f"Proposal {path.name} changed after it was reviewed.",
            ["Review the changed proposal again before importing it."],
        )
    _verify_proposal_payload(path, entry)


def reviewed_proposal_paths(workspace: Workspace, directory: Path) -> tuple[list[Path], dict[str, Any]]:
    """Select only current, reviewed manifest entries from a proposal directory."""
    directory = directory.resolve()
    manifest_path, manifest = _load_manifest(directory)
    entries = _manifest_entries(workspace, directory, manifest)
    reviewed = [entry for entry in entries if bool(entry.get("reviewed"))]
    if not reviewed:
        raise DocumentledgerError(
            "mapping_review_required",
            "The proposal manifest has no reviewed entries.",
            ["Inspect generated proposal files, then run `documentledger link import-map --directory DIR --review`."],
        )
    paths: list[Path] = []
    for entry in reviewed:
        path = directory / str(entry["filename"])
        _validate_reviewed_entry(path, entry)
        paths.append(path)
    owned = _entry_filenames(manifest) | {PROPOSAL_MANIFEST_NAME}
    unowned = sorted(path.name for path in directory.glob("*.yaml") if path.name not in owned)
    unreviewed = sorted(str(entry["doc_path"]) for entry in entries if not bool(entry.get("reviewed")))
    return paths, {
        "manifest": str(manifest_path),
        "unowned_mapping_files": unowned,
        "unreviewed_documents": unreviewed,
        "reviewed_documents": sorted(str(entry["doc_path"]) for entry in reviewed),
    }


def require_reviewed_manifest_file(workspace: Workspace, mapping_path: Path) -> bool:
    """Require a reviewed manifest entry when an explicit file belongs to a batch."""
    mapping_path = mapping_path.resolve()
    manifest_path = mapping_path.parent / PROPOSAL_MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return False
    _, manifest = _load_manifest(mapping_path.parent)
    entries = _manifest_entries(workspace, mapping_path.parent, manifest)
    entry = next((item for item in entries if str(item["filename"]) == mapping_path.name), None)
    if entry is None:
        raise DocumentledgerError(
            "unowned_mapping_file",
            f"Mapping file {mapping_path.name} is not listed in the adjacent proposal manifest.",
            ["Import only reviewed manifest entries, or move a standalone mapping to a separate directory."],
        )
    _validate_reviewed_entry(mapping_path, entry)
    return True
