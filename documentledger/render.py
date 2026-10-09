from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ledgercore.hashing import sha256_text

from documentledger.doc_index import doc_sections_for_file
from documentledger.errors import DocumentledgerError
from documentledger.impact import resolve_affected_sections, stale_doc_details
from documentledger.links import current_source_inventory
from documentledger.models import Workspace
from documentledger.storage import iter_doc_records, latest_scan, state_version, workspace_root


def stale_details(workspace: Workspace) -> list[dict[str, Any]]:
    return stale_doc_details(workspace)


def section_text_map(workspace: Workspace, doc_path: str) -> dict[str, dict[str, Any]]:
    target = workspace_root(workspace) / doc_path
    if not target.exists():
        return {}
    return {section.section_id: section.to_record() | {"text": section.text} for section in doc_sections_for_file(target, doc_path)}


def source_snippet(root: Path, source_path: str, line_span: list[int], *, max_lines: int) -> str:
    path = root / source_path
    if not path.exists():
        return "(source no longer exists)"
    start, end = line_span
    lines = path.read_text(encoding="utf-8").splitlines()
    excerpt = lines[max(0, start - 1) : min(len(lines), end)]
    if max_lines > 0:
        excerpt = excerpt[:max_lines]
    return "\n".join(excerpt).strip("\n")


def trim_lines(text: str, *, max_lines: int) -> list[str]:
    lines = text.splitlines()
    if max_lines > 0:
        lines = lines[:max_lines]
    return lines or ["(empty)"]


def linked_sections(workspace: Workspace, docs: list[str] | None = None, section_id: str | None = None) -> list[dict[str, Any]]:
    selected_docs = set(docs) if docs is not None else None
    items: list[dict[str, Any]] = []
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        if selected_docs is not None and doc_path not in selected_docs:
            continue
        sections_by_id = section_text_map(workspace, doc_path)
        for section in record.get("sections", []) or []:
            if section_id is not None and str(section.get("heading_slug")) != section_id and str(section.get("section_id")) != section_id:
                continue
            if not list(section.get("links", []) or []):
                continue
            text_record = sections_by_id.get(str(section.get("section_id")), {})
            items.append(
                {
                    "doc_path": doc_path,
                    "section_id": str(section.get("section_id", "")),
                    "heading_path": list(section.get("heading_path", []) or []),
                    "heading_slug": str(section.get("heading_slug", "")),
                    "line_span": list(section.get("line_span", [0, 0])),
                    "section_hash": str(section.get("section_hash", "")),
                    "summary": str(section.get("summary", "")),
                    "action": "review-section",
                    "changed_units": [
                        {
                            "source_id": str(link.get("source_id", "")),
                            "source_path": str(link.get("source_path", "")),
                            "line_span": [0, 0],
                            "changed_hashes": sorted(dict(link.get("tracked_hashes", {})).keys()) or ["file_hash"],
                            "reason": str(link.get("reason", "")),
                        }
                        for link in (section.get("links", []) or [])
                    ],
                    "text": str(text_record.get("text", "")).strip("\n"),
                }
            )
    return sorted(items, key=lambda item: (str(item["doc_path"]), str(item["section_id"])))


def selected_doc_sections(workspace: Workspace, docs: list[str], section_id: str | None = None) -> list[dict[str, Any]]:
    record_map = {str(record.get("doc_path", "")): record for record in iter_doc_records(workspace)}
    items: list[dict[str, Any]] = []
    for doc_path in docs:
        sections_by_id = section_text_map(workspace, doc_path)
        record_sections = {
            str(section.get("section_id", "")): dict(section) for section in (record_map.get(doc_path, {}).get("sections", []) or [])
        }
        for section in doc_sections_for_file(workspace_root(workspace) / doc_path, doc_path):
            if section_id is not None and section.heading_slug != section_id and section.section_id != section_id:
                continue
            record_section = record_sections.get(section.section_id, {})
            links = list(record_section.get("links", []) or [])
            items.append(
                {
                    "doc_path": doc_path,
                    "section_id": section.section_id,
                    "heading_path": list(section.heading_path),
                    "heading_slug": section.heading_slug,
                    "line_span": [section.line_span[0], section.line_span[1]],
                    "section_hash": section.section_hash,
                    "summary": section.summary,
                    "action": "review-section",
                    "changed_units": [
                        {
                            "source_id": str(link.get("source_id", "")),
                            "source_path": str(link.get("source_path", "")),
                            "line_span": [0, 0],
                            "changed_hashes": sorted(dict(link.get("tracked_hashes", {})).keys()) or ["file_hash"],
                            "reason": str(link.get("reason", "")),
                        }
                        for link in links
                    ],
                    "text": str(sections_by_id.get(section.section_id, {}).get("text", "")).strip("\n"),
                }
            )
    return sorted(items, key=lambda item: (str(item["doc_path"]), str(item["section_id"])))


def enrich_linked_source_units(workspace: Workspace, sections: list[dict[str, Any]]) -> None:
    """Resolve every rendered link against the current source inventory."""
    inventory = current_source_inventory(workspace)
    for section in sections:
        for unit in section.get("changed_units", []) or []:
            source_id = str(unit.get("source_id", ""))
            current = inventory.get(source_id)
            if current is None:
                unit["missing"] = True
                unit["line_span"] = [0, 0]
                continue
            unit["missing"] = False
            unit["source_path"] = str(current.get("path", unit.get("source_path", "")))
            unit["line_span"] = list(current.get("line_span", [0, 0]))
            unit["kind"] = str(current.get("kind", ""))
            unit["signature"] = str(current.get("signature", ""))


def bootstrap_inventory(workspace: Workspace, scan: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    all_docs = sorted((scan.get("doc_hashes", {}) or {}).keys()) if scan else []
    all_sources = set((scan.get("source_hashes", {}) or {}).keys()) if scan else set()
    linked_sources: set[str] = set()
    for record in iter_doc_records(workspace):
        linked_sources.update(str(source) for source in (record.get("linked_sources", []) or []))
    return sorted(all_sources - linked_sources), all_docs


def source_role(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    parts = normalized.split("/")
    return "test" if "tests" in parts or normalized.startswith("test") or Path(normalized).name.startswith("test_") else "production"


def bootstrap_source_records(workspace: Workspace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = current_source_inventory(workspace)
    production = [dict(unit) for unit in inventory.values() if source_role(str(unit.get("path", ""))) == "production"]
    tests = [dict(unit) for unit in inventory.values() if source_role(str(unit.get("path", ""))) == "test"]

    def unit_key(unit: dict[str, Any]) -> tuple[str, str, str]:
        return (str(unit.get("path", "")), str(unit.get("line_span", [0, 0])[0]), str(unit.get("source_id", "")))

    return sorted(production, key=unit_key), sorted(tests, key=unit_key)


def _context_selector_hash(
    mode: str,
    docs: list[str] | None,
    section_id: str | None,
    include_unlinked: bool,
    max_source_lines: int,
    max_section_lines: int,
) -> str:
    selector = {
        "mode": mode,
        "docs": sorted(docs or []),
        "section_id": section_id,
        "include_unlinked": include_unlinked,
        "max_source_lines": max_source_lines,
        "max_section_lines": max_section_lines,
    }
    return sha256_text(json.dumps(selector, sort_keys=True, separators=(",", ":")))[:16]


def _context_manifest_hash(workspace: Workspace, specs: list[dict[str, Any]], extra_paths: list[str]) -> str:
    root = workspace_root(workspace)
    paths = set(extra_paths)
    units: list[dict[str, Any]] = []
    for spec in specs:
        descriptor: dict[str, Any] = {"unit_id": str(spec.get("unit_id", "")), "unit_type": spec.get("unit_type", "")}
        if spec["unit_type"] == "source":
            unit = spec["source_unit"]
            source_path = str(unit.get("path", ""))
            paths.add(source_path)
            descriptor.update(
                {
                    "role": spec.get("role"),
                    "path": source_path,
                    "line_span": unit.get("line_span"),
                    "signature": unit.get("signature"),
                }
            )
        elif spec["unit_type"] == "section":
            item = spec["section"]
            paths.add(str(item.get("doc_path", "")))
            source_paths = [str(unit.get("source_path", "")) for unit in item.get("changed_units", []) or []]
            paths.update(source_paths)
            descriptor.update({"doc_path": item.get("doc_path"), "section_id": item.get("section_id"), "sources": source_paths})
        elif spec["unit_type"] == "unlinked-source":
            paths.add(str(spec.get("source_path", "")))
        units.append(descriptor)

    file_hashes: dict[str, str] = {}
    for relative_path in sorted(path for path in paths if path):
        target = root / relative_path
        try:
            digest = hashlib.sha256()
            with target.open("rb") as source_file:
                while chunk := source_file.read(65_536):
                    digest.update(chunk)
            file_hashes[relative_path] = digest.hexdigest()
        except OSError:
            file_hashes[relative_path] = "missing-or-unreadable"
    manifest = {"units": units, "files": file_hashes}
    return sha256_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))[:16]


def _context_cursor(
    scan_version: int,
    state_version_value: int,
    source_index_hash: str,
    selector_hash: str,
    manifest_hash: str,
    offset: int,
) -> str:
    return f"dlctx1:{scan_version}:{state_version_value}:{source_index_hash[:16] or '-'}:{selector_hash}:{manifest_hash}:{offset}"


def _context_offset(
    cursor: str | None,
    *,
    scan_version: int,
    state_version_value: int,
    source_index_hash: str,
    selector_hash: str,
    manifest_hash: str,
) -> int:
    if not cursor:
        return 0
    parts = cursor.split(":")
    if len(parts) != 7 or parts[0] != "dlctx1":
        raise DocumentledgerError(
            "invalid_context_cursor",
            "The context continuation cursor is malformed or unsupported.",
            ["Copy the exact `next_cursor` from the preceding context result."],
        )
    try:
        cursor_scan = int(parts[1])
        cursor_state = int(parts[2])
        offset = int(parts[6])
    except ValueError as exc:
        raise DocumentledgerError("invalid_context_cursor", "The context continuation cursor contains invalid numbers.") from exc
    expected_index_hash = source_index_hash[:16] or "-"
    if (
        cursor_scan != scan_version
        or cursor_state != state_version_value
        or parts[3] != expected_index_hash
        or parts[4] != selector_hash
        or parts[5] != manifest_hash
    ):
        raise DocumentledgerError(
            "context_cursor_stale",
            "The context cursor does not match the current scan, state, selector, or evidence manifest.",
            ["Start a new context export or restore the matching scan and selectors."],
            details={"cursor_scan_version": cursor_scan, "current_scan_version": scan_version},
        )
    if offset < 0:
        raise DocumentledgerError("invalid_context_cursor", "The context continuation cursor has a negative offset.")
    return offset


def _source_context_lines(workspace: Workspace, unit: dict[str, Any], role: str, max_source_lines: int) -> list[str]:
    source_id = str(unit.get("source_id", ""))
    source_path = str(unit.get("path", ""))
    span = list(unit.get("line_span", [0, 0]))
    lines = [
        f"### {source_id}",
        f"- role: {role.lower()}",
        f"- path: {source_path}",
        f"- kind: {unit.get('kind', '')}",
        f"- signature: `{unit.get('signature', '')}`",
        f"- lines: {span[0]}-{span[1]}",
        "",
        "```python",
        source_snippet(workspace_root(workspace), source_path, span, max_lines=max_source_lines),
        "```",
        "",
    ]
    return lines


def _section_context_lines(workspace: Workspace, item: dict[str, Any], max_source_lines: int, max_section_lines: int) -> list[str]:
    doc_path = str(item["doc_path"])
    heading_path = " / ".join(item.get("heading_path", []) or []) or str(item["section_id"])
    block = [
        f"### {doc_path} :: {heading_path}",
        "",
        f"Section id: {item['section_id']}",
        f"Lines: {item['line_span'][0]}-{item['line_span'][1]}",
        f"Action: {item['action']}",
        "",
        "Linked source units:",
        "",
    ]
    for unit in item.get("changed_units", []) or []:
        block.extend(
            [
                f"- {unit['source_id']}",
                f"  - path: {unit['source_path']}",
                f"  - status: {'missing' if unit.get('missing') else 'live'}",
                *([f"  - kind: {unit['kind']}", f"  - signature: `{unit['signature']}`"] if not unit.get("missing") else []),
                f"  - lines: {unit['line_span'][0]}-{unit['line_span'][1]}",
                f"  - changed: {', '.join(unit.get('changed_hashes', []) or ['file_hash'])}",
                f"  - reason: {unit['reason'] or 'No recorded reason.'}",
                "",
                "  Current relevant source:",
                "",
            ]
        )
        snippet = source_snippet(
            workspace_root(workspace),
            str(unit["source_path"]),
            list(unit.get("line_span", [0, 0])),
            max_lines=max_source_lines,
        )
        block.extend(f"  {line}" for line in trim_lines(snippet, max_lines=max_source_lines))
        block.append("")
    block.extend(["Current section text:", ""])
    block.extend(trim_lines(str(item.get("text", "")).strip("\n"), max_lines=max_section_lines))
    block.append("")
    return block


def _context_document(
    *,
    mode: str,
    scan_version: int,
    state_version_value: int,
    source_index_hash: str,
    manifest_hash: str,
    cursor: str | None,
    page_size: int,
    total_units: int,
    selected_units: list[dict[str, Any]],
    omitted: list[str],
    next_cursor: str | None,
    body: list[str],
) -> str:
    truncated = bool(omitted)
    status = "INCOMPLETE" if truncated else "COMPLETE"
    next_label = next_cursor or "none"
    checksums = [{"unit_id": str(unit["unit_id"]), "sha256": str(unit["checksum"])} for unit in selected_units]
    front_matter = [
        "---",
        "documentledger_schema: documentledger.context.v5",
        f"scan_version: {scan_version}",
        f"state_version: {state_version_value}",
        f"mode: {mode}",
        f"source_index_hash: {json.dumps(source_index_hash)}",
        f"manifest_hash: {json.dumps(manifest_hash)}",
        f"cursor: {json.dumps(cursor or '')}",
        f"page_size: {page_size}",
        f"truncated: {str(truncated).lower()}",
        f"omitted: {json.dumps(omitted, ensure_ascii=False, separators=(',', ':'))}",
        f"total_units: {total_units}",
        f"emitted_units: {len(selected_units)}",
        f"emitted_unit_ids: {json.dumps([str(unit['unit_id']) for unit in selected_units], ensure_ascii=False, separators=(',', ':'))}",
        f"unit_checksums: {json.dumps(checksums, ensure_ascii=False, separators=(',', ':'))}",
        f"next_cursor: {json.dumps(next_cursor or '')}",
        "---",
        "",
    ]
    banner = f"<!-- DOCUMENTLEDGER CONTEXT: {status}; scan={scan_version}; units={len(selected_units)}/{total_units}; next={next_label} -->"
    return "\n".join([banner, *front_matter, *body]).rstrip() + "\n"


def _bootstrap_context_body(
    selected_units: list[dict[str, Any]],
    *,
    bootstrap_docs: list[str],
    bootstrap_sources: list[str],
    total_source_units: int,
) -> list[str]:
    body = ["# Documentation update context", "", "## Repository documentation outline", ""]
    body.extend([f"- {doc}" for doc in bootstrap_docs] or ["- None"])
    body.extend(
        [
            "",
            "## Unlinked source inventory",
            "",
            f"- {len(bootstrap_sources)} unlinked source file(s) in the current scan.",
            "",
            "## Production source outline",
            "",
        ]
    )
    for spec in selected_units:
        if spec["role"] == "Production":
            unit = spec["source_unit"]
            body.append(f"- {spec['unit_id']} — `{unit.get('signature', '')}`")
    body.extend(["", "## Test source outline", ""])
    for spec in selected_units:
        if spec["role"] == "Test":
            unit = spec["source_unit"]
            body.append(f"- {spec['unit_id']} — `{unit.get('signature', '')}`")
    body.extend(["", "## High-value source evidence", ""])
    for spec in selected_units:
        body.extend(spec["lines"])
    cli_units = [spec for spec in selected_units if spec["unit_type"] == "source" and "/cli" in str(spec["source_unit"].get("path", ""))]
    body.extend(["## CLI command inventory", ""])
    body.extend([f"- {spec['unit_id']} — `{spec['source_unit'].get('signature', '')}`" for spec in cli_units] or ["- None detected"])
    body.extend(
        [
            "",
            "## Bootstrap counts",
            "",
            f"- documents: {len(bootstrap_docs)}",
            f"- source units: {total_source_units}",
            f"- source units emitted on this page: {len(selected_units)}",
            f"- unlinked source files: {len(bootstrap_sources)}",
            "",
        ]
    )
    return body


def _selected_context_body(
    mode: str,
    selected_units: list[dict[str, Any]],
    *,
    has_specs: bool,
    include_unlinked: bool,
    has_unlinked_sources: bool,
    unlinked_changed: list[str],
    validation_commands: list[str],
) -> list[str]:
    heading = {
        "affected": "## Affected documentation sections",
        "all": "## Linked documentation sections",
        "doc": "## Selected documentation sections",
    }[mode]
    body = ["# Documentation update context", "", heading, ""]
    if not has_specs:
        body.extend(["No sections matched the selector.", ""])
    has_unlinked_heading = False
    for spec in selected_units:
        if spec["unit_type"] == "section":
            body.extend(spec["lines"])
        else:
            if not has_unlinked_heading:
                body.extend(["## Unlinked sources (bootstrap)", ""])
                has_unlinked_heading = True
            body.extend(spec["lines"])
    if include_unlinked and not has_unlinked_sources and not has_unlinked_heading:
        body.extend(["## Unlinked sources (bootstrap)", "", "- None", ""])
    body.extend(["## Unlinked changed sources", "", *([f"- {source}" for source in unlinked_changed] or ["- None"]), ""])
    body.extend(
        [
            "## Validation commands",
            "",
            *([f"- `{command}`" for command in validation_commands] or ["- None configured"]),
            "",
            "## Agent rules",
            "",
            "- Inspect affected or selected source units before editing docs.",
            "- Rewrite only the selected sections unless broader consistency requires more.",
            "- Do not invent behavior.",
            "- Run the configured validation commands when they exist.",
            (
                '- Run `documentledger document mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version '
                'VERSION."` only after docs are updated and validated.'
            ),
            "",
        ]
    )
    return body


def render_context(  # noqa: C901
    workspace: Workspace,
    *,
    mode: str,
    docs: list[str] | None = None,
    section_id: str | None = None,
    include_unlinked: bool = False,
    max_source_lines: int = 40,
    max_section_lines: int = 80,
    max_bytes: int = 250_000,
    cursor: str | None = None,
    page_size: int = 40,
) -> dict[str, Any]:
    if page_size < 1 or page_size > 100:
        raise DocumentledgerError("invalid_page_size", "Context page size must be between 1 and 100.")
    scan = latest_scan(workspace)
    scan_version = int(scan.get("version", 0)) if scan else 0
    state_version_value = state_version(workspace)
    source_index_hash = str((scan or {}).get("source_index_hash", ""))
    selector_hash = _context_selector_hash(
        mode,
        docs,
        section_id,
        include_unlinked,
        max_source_lines,
        max_section_lines,
    )
    bootstrap_sources, bootstrap_docs = bootstrap_inventory(workspace, scan)

    if mode == "affected":
        selected_sections = resolve_affected_sections(workspace, scan=scan, docs=docs, section_id=section_id)
        for item in selected_sections:
            item["text"] = str(section_text_map(workspace, str(item["doc_path"])).get(str(item["section_id"]), {}).get("text", "")).strip(
                "\n"
            )
    elif mode == "all":
        selected_sections = linked_sections(workspace, docs=docs, section_id=section_id)
    elif mode == "doc":
        selected_sections = selected_doc_sections(workspace, docs or [], section_id=section_id)
    elif mode == "bootstrap":
        selected_sections = []
    else:
        raise DocumentledgerError("invalid_context_mode", f"Unsupported render mode: {mode}")

    if mode != "bootstrap":
        enrich_linked_source_units(workspace, selected_sections)

    unlinked_changed = list(scan.get("unlinked_changed_sources", []) or []) if scan else []
    source_unit_count = sum(len(item.get("changed_units", []) or []) for item in selected_sections)
    specs: list[dict[str, Any]] = []
    if mode == "bootstrap":
        production_units, test_units = bootstrap_source_records(workspace)
        source_unit_count = len(production_units) + len(test_units)
        for role, units in (("Production", production_units), ("Test", test_units)):
            for unit in units:
                source_id = str(unit.get("source_id", ""))
                if not source_id:
                    continue
                specs.append({"unit_id": source_id, "unit_type": "source", "role": role, "source_unit": unit})
    else:
        for item in selected_sections:
            specs.append(
                {
                    "unit_id": f"section:{item['doc_path']}::{item['section_id']}",
                    "unit_type": "section",
                    "section": item,
                }
            )
        if include_unlinked:
            for source_path in bootstrap_sources:
                specs.append({"unit_id": f"unlinked-source:{source_path}", "unit_type": "unlinked-source", "source_path": source_path})

    manifest_hash = _context_manifest_hash(workspace, specs, [*bootstrap_sources, *bootstrap_docs])
    request_offset = _context_offset(
        cursor,
        scan_version=scan_version,
        state_version_value=state_version_value,
        source_index_hash=source_index_hash,
        selector_hash=selector_hash,
        manifest_hash=manifest_hash,
    )
    if request_offset > len(specs) or (request_offset == len(specs) and specs):
        raise DocumentledgerError("invalid_context_cursor", "The context cursor points beyond the available evidence units.")
    candidate_specs = specs[request_offset : request_offset + page_size]
    rendered_candidates: list[dict[str, Any]] = []
    for spec in candidate_specs:
        if spec["unit_type"] == "source":
            lines = _source_context_lines(workspace, spec["source_unit"], str(spec["role"]), max_source_lines)
        elif spec["unit_type"] == "section":
            lines = _section_context_lines(workspace, spec["section"], max_source_lines, max_section_lines)
        else:
            lines = [f"- {spec['source_path']}", ""]
        rendered_candidates.append(spec | {"lines": lines, "checksum": sha256_text("\n".join(lines))})

    chosen: dict[str, Any] | None = None
    metadata_only_bytes = 0
    for emitted_count in range(len(rendered_candidates), -1, -1):
        selected_units = rendered_candidates[:emitted_count]
        omitted = [str(spec["unit_id"]) for spec in specs[request_offset + emitted_count :]]
        next_cursor = (
            _context_cursor(
                scan_version,
                state_version_value,
                source_index_hash,
                selector_hash,
                manifest_hash,
                request_offset + emitted_count,
            )
            if omitted
            else None
        )
        content = _context_document(
            mode=mode,
            scan_version=scan_version,
            state_version_value=state_version_value,
            source_index_hash=source_index_hash,
            manifest_hash=manifest_hash,
            cursor=cursor,
            page_size=page_size,
            total_units=len(specs),
            selected_units=selected_units,
            omitted=omitted,
            next_cursor=next_cursor,
            body=(
                _bootstrap_context_body(
                    selected_units,
                    bootstrap_docs=bootstrap_docs,
                    bootstrap_sources=bootstrap_sources,
                    total_source_units=source_unit_count,
                )
                if mode == "bootstrap"
                else _selected_context_body(
                    mode,
                    selected_units,
                    has_specs=bool(selected_sections),
                    include_unlinked=include_unlinked,
                    has_unlinked_sources=bool(bootstrap_sources),
                    unlinked_changed=unlinked_changed,
                    validation_commands=list(workspace.config.validation_commands),
                )
            ),
        )
        content_bytes = len(content.encode("utf-8"))
        if emitted_count == 0:
            metadata_only_bytes = content_bytes
        if max_bytes <= 0 or content_bytes <= max_bytes:
            chosen = {
                "content": content,
                "truncated": bool(omitted),
                "omitted": omitted,
                "next_cursor": next_cursor,
                "selected_units": selected_units,
            }
            break
    if chosen is None:
        raise DocumentledgerError(
            "context_metadata_exceeds_limit",
            "The context completeness manifest does not fit within --max-bytes.",
            ["Increase --max-bytes or use a smaller --page-size; no incomplete output was written."],
            details={
                "max_bytes": max_bytes,
                "minimum_required_bytes": metadata_only_bytes,
                "total_units": len(specs),
                "emitted_units": 0,
                "omitted": [str(spec["unit_id"]) for spec in specs[request_offset:]],
                "next_cursor": _context_cursor(
                    scan_version,
                    state_version_value,
                    source_index_hash,
                    selector_hash,
                    manifest_hash,
                    request_offset,
                )
                if request_offset < len(specs)
                else None,
            },
        )

    content = str(chosen["content"])
    selected_units = list(chosen["selected_units"])
    total_documents = len({str(item["doc_path"]) for item in selected_sections}) if selected_sections else len(bootstrap_docs)
    return {
        "content": content,
        "mode": mode,
        "documents": total_documents,
        "sections": len(selected_sections),
        "source_units": source_unit_count,
        "bytes": len(content.encode("utf-8")),
        "truncated": bool(chosen["truncated"]),
        "omitted": list(chosen["omitted"]),
        "total_units": len(specs),
        "emitted_units": len(selected_units),
        "emitted_unit_ids": [str(unit["unit_id"]) for unit in selected_units],
        "unit_checksums": [{"unit_id": str(unit["unit_id"]), "sha256": str(unit["checksum"])} for unit in selected_units],
        "next_cursor": chosen["next_cursor"],
        "cursor": cursor,
        "page_size": page_size,
        "scan_version": scan_version,
        "state_version": state_version_value,
        "source_index_hash": source_index_hash,
        "manifest_hash": manifest_hash,
    }
