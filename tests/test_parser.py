"""Tests for the Markdown parser."""

from paper2beamer.core.parser import MarkdownParser
from paper2beamer.core.models import BlockType


def test_parse_title_and_authors(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    assert doc.title == "Test Paper Title"
    assert "Author One" in doc.authors
    assert "Author Two" in doc.authors


def test_parse_abstract(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    assert "abstract" in doc.abstract.lower()
    assert len(doc.abstract) > 0


def test_parse_sections(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    assert len(doc.sections) >= 1

    intro = None
    for s in doc.sections:
        if "Introduction" in s.title:
            intro = s
            break
    assert intro is not None
    assert len(intro.blocks) > 0


def test_parse_formula_detection(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    all_text = doc.abstract
    for s in doc.sections:
        for b in s.blocks:
            all_text += b.content

    assert "$$" in all_text


def test_parse_citations(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    assert len(doc.citations) > 0
    keys = [c.key for c in doc.citations]
    assert any("test2024" in k for k in keys)


def _all_blocks(sections):
    for s in sections:
        yield from s.blocks
        yield from _all_blocks(s.subsections)


def test_parse_figure(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    has_figure = any(
        b.type == BlockType.FIGURE for b in _all_blocks(doc.sections)
    )
    assert has_figure


def test_parse_table(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    has_table = any(
        b.type == BlockType.TABLE for b in _all_blocks(doc.sections)
    )
    assert has_table


def test_parse_references(sample_markdown):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    assert len(doc.references_raw) > 0
    assert "Test Author" in doc.references_raw
