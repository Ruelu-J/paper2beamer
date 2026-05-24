"""Tests for the frame splitter."""

from paper2beamer.core.parser import MarkdownParser
from paper2beamer.core.converter import BeamerConverter
from paper2beamer.core.splitter import FrameSplitter
from paper2beamer.core.models import OutputMode


def test_splitter_preserves_content(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    splitter = FrameSplitter()
    result = splitter.split(tex)

    assert r"\begin{document}" in result
    assert r"\end{document}" in result
    assert r"\begin{frame}" in result
    assert r"\end{frame}" in result


def test_splitter_does_not_lose_frames(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    splitter = FrameSplitter()
    result = splitter.split(tex)

    original_frames = tex.count(r"\begin{frame}")
    result_frames = result.count(r"\begin{frame}")
    assert result_frames >= original_frames


def test_splitter_matching_frame_counts(sample_markdown, default_template_dir):
    parser = MarkdownParser()
    doc = parser.parse(sample_markdown, "images/")
    converter = BeamerConverter()
    tex = converter.convert(doc, default_template_dir, OutputMode.FULL)
    splitter = FrameSplitter()
    result = splitter.split(tex)

    open_count = result.count(r"\begin{frame}")
    close_count = result.count(r"\end{frame}")
    assert open_count == close_count
    assert open_count > 0
