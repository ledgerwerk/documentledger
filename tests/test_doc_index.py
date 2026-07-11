from __future__ import annotations

from documentledger.doc_index import markdown_sections


def test_markdown_sections_ignore_headings_inside_backtick_fences() -> None:
    sections = markdown_sections(
        "docs/example.md",
        "# Intro\n\n```bash\n# comment\n## another comment\n```\n\n## Real heading\n",
    )
    assert [section.heading_slug for section in sections] == ["intro", "real-heading"]


def test_markdown_sections_ignore_headings_inside_tilde_fences() -> None:
    sections = markdown_sections(
        "docs/example.md",
        "# Intro\n\n~~~text\n## hidden\n~~~\n\n## Visible\n",
    )
    assert [section.heading_slug for section in sections] == ["intro", "visible"]


def test_markdown_sections_normalize_trailing_hashes() -> None:
    sections = markdown_sections("docs/example.md", "## Heading ##\nBody\n")
    assert [section.heading_slug for section in sections] == ["heading"]


def test_markdown_sections_keep_line_spans_after_closing_fence() -> None:
    sections = markdown_sections(
        "docs/example.md",
        "# Intro\n\n```bash\n# hidden\n```\n\n## Visible\nBody\n",
    )
    assert sections[1].line_span == (7, 8)
