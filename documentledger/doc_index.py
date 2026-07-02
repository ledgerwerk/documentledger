from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict

from ledgercore.hashing import sha256_text
from ledgercore.ids import slugify_ref

from documentledger.errors import DocumentledgerError
from documentledger.models import DocSection

MARKER_RE = re.compile(r"<!--\s*docledger-section:\s*([a-zA-Z0-9][a-zA-Z0-9_-]*)\s*-->")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


class HeadingRecord(TypedDict):
    line: int
    title: str
    heading_path: list[str]
    slug: str
    marker: str | None


def section_identity(doc_path: str, marker: str | None, slug: str) -> str:
    return f"md:section:{doc_path}::{marker or slug}"


def whole_doc_section(doc_path: str, text: str) -> DocSection:
    lines = text.splitlines()
    content = text.strip("\n")
    return DocSection(
        section_id=section_identity(doc_path, "whole-doc", "whole-doc"),
        doc_path=doc_path,
        heading_path=[],
        heading_slug="whole-doc",
        line_span=(1, max(len(lines), 1)),
        section_hash=sha256_text(content),
        summary="Whole document.",
        text=content,
    )


def summarize_section(heading: str, content: str) -> str:
    if heading:
        return heading
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "Whole document."


def markdown_sections(doc_path: str, text: str) -> list[DocSection]:
    lines = text.splitlines()
    marker_lines: dict[int, str] = {}
    seen_markers: set[str] = set()
    for number, line in enumerate(lines, start=1):
        match = MARKER_RE.fullmatch(line.strip())
        if not match:
            continue
        marker = match.group(1)
        if marker in seen_markers:
            raise DocumentledgerError("duplicate_section_marker", f"Duplicate doc section marker: {marker}")
        seen_markers.add(marker)
        marker_lines[number] = marker

    headings: list[HeadingRecord] = []
    slug_counts: dict[str, int] = {}
    path_stack: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        match = HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
        path_stack.append((level, title))
        base_slug = slugify_ref(title, empty="section")
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1
        slug = base_slug if slug_counts[base_slug] == 1 else f"{base_slug}-{slug_counts[base_slug]}"
        marker = marker_lines.get(number - 1)
        headings.append(
            {
                "line": number,
                "title": title,
                "heading_path": [item[1] for item in path_stack],
                "slug": slug,
                "marker": marker,
            }
        )
    if not headings:
        return [whole_doc_section(doc_path, text)]

    sections: list[DocSection] = []
    for index, heading in enumerate(headings):
        start_line = int(heading["line"])
        next_line = int(headings[index + 1]["line"]) - 1 if index + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start_line - 1 : next_line]).strip("\n")
        title = str(heading["title"])
        slug = str(heading["slug"])
        marker = str(heading["marker"]) if heading["marker"] is not None else None
        sections.append(
            DocSection(
                section_id=section_identity(doc_path, marker, slug),
                doc_path=doc_path,
                heading_path=list(heading["heading_path"]),
                heading_slug=marker or slug,
                line_span=(start_line, max(start_line, next_line)),
                section_hash=sha256_text(content),
                summary=summarize_section(title, content),
                text=content,
            )
        )
    return sections


def doc_sections_for_file(path: Path, repo_path: str) -> list[DocSection]:
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".md":
        return [whole_doc_section(repo_path, text)]
    return markdown_sections(repo_path, text)
