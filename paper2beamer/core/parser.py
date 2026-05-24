"""Markdown parser — converts MinerU output into a structured Document."""

import re
from pathlib import Path

from paper2beamer.core.models import (
    Block, BlockType, Document, Section, Citation
)


class MarkdownParser:
    def parse(self, markdown_text: str, images_dir: str) -> Document:
        lines = markdown_text.splitlines(keepends=False)
        lines = self._preprocess(lines, images_dir)

        title = ""
        authors: list[str] = []
        abstract = ""
        sections: list[Section] = []

        i = 0
        n = len(lines)

        i, title = self._parse_title(lines, i)
        i, authors = self._parse_authors(lines, i)
        i, abstract = self._parse_abstract(lines, i)
        sections, references_raw = self._parse_body(lines, i)

        doc = Document(
            title=title,
            authors=authors,
            abstract=abstract,
            sections=sections,
            citations=[],
            references_raw=references_raw,
            images_dir=images_dir,
        )
        doc.citations = self._extract_citations_from_doc(doc)
        return doc

    def _preprocess(self, lines: list[str], images_dir: str) -> list[str]:
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped:
                result.append(stripped)
            else:
                if result and result[-1] != "":
                    result.append("")
        return result

    def _parse_title(self, lines: list[str], i: int) -> tuple[int, str]:
        if i < len(lines) and lines[i].startswith("# "):
            title = lines[i][2:].strip()
            return i + 1, title
        if i < len(lines):
            return i + 1, lines[i]
        return i, ""

    def _parse_authors(self, lines: list[str], i: int) -> tuple[int, list[str]]:
        authors: list[str] = []
        while i < len(lines) and lines[i] == "":
            i += 1

        if i >= len(lines):
            return i, authors

        line = lines[i]
        if line.startswith("#"):
            return i, authors

        line = re.sub(r'\bBY\b\s*', '', line)
        line = re.sub(r'\d+\s*,?\s*', '', line)
        line = re.sub(r'[\d,]+$', '', line)
        line = re.sub(r'\([^)]*\)', '', line)

        for sep in [', AND ', ', and ', ' AND ', ' and ', ',']:
            if sep in line:
                parts = [p.strip() for p in line.split(sep) if p.strip()]
                authors = [p for p in parts if len(p) > 1]
                break
        else:
            if len(line) > 3:
                authors = [line.strip()]

        authors = [re.sub(r'\s+', ' ', a).strip() for a in authors]
        return i + 1, authors

    def _parse_abstract(self, lines: list[str], i: int) -> tuple[int, str]:
        while i < len(lines) and lines[i] == "":
            i += 1

        # Check for explicit abstract heading
        if i < len(lines):
            if re.match(r"^#{1,3}\s*abstract", lines[i], re.IGNORECASE):
                i += 1
                abstract_lines: list[str] = []
                while i < len(lines):
                    line = lines[i]
                    if re.match(r"^#{1,6}\s", line):
                        break
                    if line == "" and abstract_lines and abstract_lines[-1] == "":
                        i += 1
                        continue
                    abstract_lines.append(line)
                    i += 1
                return i, " ".join(abstract_lines).strip()

        # No explicit abstract heading — collect text before first section
        abstract_lines: list[str] = []
        while i < len(lines):
            line = lines[i]
            if re.match(r"^#{1,6}\s", line):
                break
            if line == "" and abstract_lines and abstract_lines[-1] == "":
                i += 1
                continue
            abstract_lines.append(line)
            i += 1

        return i, " ".join(abstract_lines).strip()

    @staticmethod
    def _infer_level(heading_text: str, markdown_level: int) -> int:
        m = re.match(r'^([A-Z]|\d+)(\.\d+)*\.?\s', heading_text)
        if m:
            prefix = m.group(0).rstrip().rstrip('.')
            depth = prefix.count('.') + 1
            return min(depth, 3)
        if re.match(r'^Appendix\s+[A-Z]', heading_text, re.IGNORECASE):
            return 1
        if re.match(r'^[A-Z][a-z]', heading_text) and not re.match(r'^[A-Z]+$', heading_text):
            return markdown_level
        return min(markdown_level, 2)

    def _parse_body(
        self, lines: list[str], i: int
    ) -> tuple[list[Section], str]:
        sections: list[Section] = []
        references_raw = ""
        section_stack: list[Section] = []
        current_blocks: list[Block] = []
        buffer: list[str] = []

        def flush_buffer():
            nonlocal buffer
            if not buffer:
                return
            text = "\n".join(buffer)
            buffer.clear()
            block = self._classify_block(text)
            current_blocks.append(block)

        while i < len(lines):
            line = lines[i]

            heading_match = re.match(r"^(#{1,6})\s+(.+)", line)
            if heading_match:
                flush_buffer()
                md_level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                # Check for references
                if re.match(r"^references?$|^bibliography$",
                            heading_text, re.IGNORECASE):
                    ref_lines: list[str] = []
                    j = i + 1
                    while j < len(lines):
                        if re.match(r"^#{1,6}\s", lines[j]):
                            break
                        ref_lines.append(lines[j])
                        j += 1
                    references_raw = "\n".join(ref_lines)
                    i = j
                    continue

                # Infer section level from content
                level = self._infer_level(heading_text, md_level)

                new_section = Section(title=heading_text, level=level, blocks=[])

                # Place section at correct depth
                while section_stack and section_stack[-1].level >= level:
                    section_stack.pop()

                if not section_stack:
                    sections.append(new_section)
                else:
                    section_stack[-1].subsections.append(new_section)

                current_blocks = new_section.blocks
                section_stack.append(new_section)

                heading_block = Block(
                    type=BlockType.HEADING,
                    content=heading_text,
                    heading_level=level,
                )
                current_blocks.append(heading_block)
                i += 1
                continue

            if line == "":
                flush_buffer()
                i += 1
                continue

            buffer.append(line)
            i += 1

        flush_buffer()
        return sections, references_raw

    def _classify_block(self, text: str) -> Block:
        text_stripped = text.strip()

        # Figure
        if re.match(r"^!\[.*\]\(.+\)$", text_stripped):
            img_match = re.match(r"^!\[(.*)\]\((.+)\)$", text_stripped)
            caption = img_match.group(1) if img_match else ""
            img_path = img_match.group(2) if img_match else ""
            return Block(
                type=BlockType.FIGURE,
                content=text_stripped,
                caption=caption,
                image_path=img_path,
            )

        # Display formula
        if text_stripped.startswith("$$") and text_stripped.endswith("$$"):
            return Block(type=BlockType.FORMULA_DISPLAY, content=text_stripped)

        # Multi-line display formula ($$ not on same line)
        if text_stripped.startswith("$$") or text_stripped.endswith("$$"):
            return Block(type=BlockType.FORMULA_DISPLAY, content=text_stripped)

        # Table
        lines = text_stripped.splitlines()
        if len(lines) >= 2:
            pipe_lines = [ln for ln in lines if ln.strip()]
            if len(pipe_lines) >= 2 and all(
                "|" in ln for ln in pipe_lines
            ):
                return Block(
                    type=BlockType.TABLE,
                    content=text_stripped,
                    lines=lines,
                )

        # Code block
        if text_stripped.startswith("```"):
            return Block(type=BlockType.CODE_BLOCK, content=text_stripped)

        # Single list item
        if len(lines) == 1 and re.match(r"^[-*]\s", text_stripped):
            return Block(
                type=BlockType.LIST_ITEM,
                content=text_stripped[2:].strip(),
            )

        # Enum item
        if len(lines) == 1 and re.match(r"^\d+\.\s", text_stripped):
            return Block(
                type=BlockType.ENUM_ITEM,
                content=re.sub(r"^\d+\.\s", "", text_stripped).strip(),
            )

        # Multi-line: check if all are list items
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) > 1:
            if all(re.match(r"^[-*]\s", ln) for ln in non_empty):
                return Block(type=BlockType.LIST_ITEM, content=text_stripped)

        # Default: paragraph
        return Block(type=BlockType.PARAGRAPH, content=text_stripped)

    def _extract_citations_from_doc(self, doc: Document) -> list[Citation]:
        citations: list[Citation] = []
        seen: set[str] = set()

        full_text = doc.abstract + "\n"
        for section in doc.sections:
            full_text += self._section_text(section) + "\n"
        full_text += doc.references_raw

        cite_pattern = re.compile(r'\\cite\{([^}]+)\}')
        for match in cite_pattern.finditer(full_text):
            keys = [k.strip() for k in match.group(1).split(",")]
            for key in keys:
                if key not in seen:
                    seen.add(key)
                    citations.append(Citation(key=key, raw_text=match.group(0)))

        bracket_pattern = re.compile(r'\[(\d+(?:[,\s]*\d+)*)\]')
        for match in bracket_pattern.finditer(full_text):
            nums = re.findall(r'\d+', match.group(1))
            for num in nums:
                key = f"ref{num}"
                if key not in seen:
                    seen.add(key)
                    citations.append(Citation(key=key, raw_text=match.group(0)))

        return citations

    def _section_text(self, section: Section) -> str:
        parts = [section.title]
        for b in section.blocks:
            parts.append(b.content)
        for sub in section.subsections:
            parts.append(self._section_text(sub))
        return "\n".join(parts)
