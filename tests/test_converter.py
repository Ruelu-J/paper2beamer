"""Tests for the Beamer converter."""

from paper2beamer.core.parser import MarkdownParser
from paper2beamer.core.converter import BeamerConverter
from paper2beamer.core.models import OutputMode


def test_convert_abstract_mode(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.ABSTRACT)
    assert r"\documentclass" in tex
    assert r"\begin{document}" in tex
    assert r"\end{document}" in tex
    assert "Abstract" in tex


def test_convert_full_mode(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    assert r"\tableofcontents" in tex
    assert r"\section" in tex or r"\subsection" in tex
    assert r"\begin{frame}" in tex


def test_convert_produces_title_slide(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    assert r"\title{Test Paper Title}" in tex
    assert r"\titlepage" in tex


def test_convert_produces_frames(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    frame_count = tex.count(r"\begin{frame}")
    assert frame_count >= 2  # title slide + at least one content frame
