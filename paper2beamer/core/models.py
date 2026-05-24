"""Domain data models for paper2beamer."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    FORMULA_DISPLAY = "formula_display"
    FORMULA_INLINE = "formula_inline"
    FIGURE = "figure"
    TABLE = "table"
    LIST_ITEM = "list_item"
    ENUM_ITEM = "enum_item"
    CODE_BLOCK = "code_block"
    CITATION = "citation"


class OutputMode(str, Enum):
    ABSTRACT = "abstract"
    FULL = "full"


@dataclass
class Block:
    type: BlockType
    content: str
    caption: str | None = None
    label: str | None = None
    image_path: str | None = None
    column_align: list[str] | None = None
    heading_level: int = 0
    lines: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    level: int
    blocks: list[Block] = field(default_factory=list)
    subsections: list["Section"] = field(default_factory=list)


@dataclass
class Citation:
    key: str
    raw_text: str = ""
    title: str | None = None
    authors: str | None = None


@dataclass
class Document:
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    sections: list[Section] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    references_raw: str = ""
    images_dir: str = ""


@dataclass
class ExtractResult:
    markdown: str
    images_dir: str
    json_path: str = ""
    pdf_hash: str = ""
    metadata: dict = field(default_factory=dict)
