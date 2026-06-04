"""Converts a Document into Beamer LaTeX source."""

import re
from pathlib import Path

from paper2beamer.core.models import (
    Block, BlockType, Document, OutputMode, Section,
)


class BeamerConverter:
    def __init__(self):
        self.figure_counter = 0
        self.table_counter = 0

    def convert(
        self,
        document: Document,
        template_dir: str = "",
        mode: OutputMode = OutputMode.FULL,
    ) -> str:
        parts: list[str] = []

        parts.append(self._build_preamble(template_dir))
        parts.append(self._build_title_slide(document))

        if mode == OutputMode.ABSTRACT:
            parts.append(self._build_abstract_frames(document))
        else:
            parts.append(r"\begin{frame}{Outline}")
            parts.append(r"\tableofcontents")
            parts.append(r"\end{frame}")
            parts.append("")
            for section in document.sections:
                parts.append(self._section_to_beamer(section))
            parts.append(self._build_thanks_slide())

        parts.append("")
        parts.append(r"\end{document}")

        return "\n".join(parts)

    def _build_preamble(self, template_dir: str) -> str:
        preamble_lines = [
            r"\documentclass[11pt,aspectratio=169]{beamer}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{amsmath,amssymb,amsthm}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{multirow}",
            r"\usepackage{array}",
            r"\usepackage{xcolor}",
            r"\usepackage{hyperref}",
            r"\usepackage{adjustbox}",
        ]

        if template_dir:
            template_path = Path(template_dir)
            sty_files = list(template_path.glob("beamertheme*.sty"))
            if not sty_files:
                sty_files = list(template_path.glob("*.sty"))
            if sty_files:
                theme_name = sty_files[0].stem
                if theme_name.startswith("beamertheme"):
                    theme_name = theme_name[len("beamertheme"):]
                preamble_lines.append(rf"\usetheme{{{theme_name}}}")
            else:
                preamble_lines.append(r"\usetheme{default}")
        else:
            preamble_lines.append(r"\usetheme{default}")

        preamble_lines.extend([
            "",
            r"\setbeamertemplate{caption}[numbered]",
            r"\setbeamertemplate{bibliography item}[text]",
            r"\allowdisplaybreaks",
            "",
            r"\AtBeginSection[]",
            r"{",
            r"  \begin{frame}{Outline}",
            r"    \tableofcontents[currentsection]",
            r"  \end{frame}",
            r"}",
            "",
            r"\AtBeginSubsection[]",
            r"{",
            r"  \begin{frame}{Outline}",
            r"    \tableofcontents[currentsection,currentsubsection]",
            r"  \end{frame}",
            r"}",
            "",
            r"\begin{document}",
        ])

        return "\n".join(preamble_lines)

    def _build_title_slide(self, document: Document) -> str:
        title = self._escape_latex(document.title)
        authors = ", ".join(self._escape_latex(a) for a in document.authors)
        return "\n".join([
            rf"\title{{{title}}}",
            rf"\author{{{authors}}}" if authors else r"\author{}",
            r"\date{\today}",
            r"\begin{frame}",
            r"  \titlepage",
            r"\end{frame}",
            "",
        ])

    def _build_abstract_frames(self, document: Document) -> str:
        frames: list[str] = []
        frames.append(
            r"\begin{frame}{Abstract}"
            "\n"
            + self._escape_latex(document.abstract or "No abstract found.")
            + "\n"
            r"\end{frame}"
        )
        return "\n\n".join(frames)

    def _section_to_beamer(self, section: Section) -> str:
        """Convert a section into Beamer with proper section/subsection commands."""
        parts: list[str] = []

        # Generate LaTeX section command
        section_title = self._escape_latex(section.title)
        if section.level == 1:
            parts.append(rf"\section{{{section_title}}}")
        else:
            parts.append(rf"\subsection{{{section_title}}}")

        # Convert blocks into frames
        frames = self._blocks_to_frames(section.title, list(section.blocks))

        if frames:
            parts.append("\n\n".join(frames))

        # Process subsections
        for sub in section.subsections:
            parts.append(self._section_to_beamer(sub))

        return "\n\n".join(parts)

    def _blocks_to_frames(self, section_title: str, blocks: list[Block]) -> list[str]:
        """Convert blocks to a sequence of frames, respecting content boundaries."""
        frames: list[str] = []
        current_frame: list[str] = []
        current_title = self._escape_latex(section_title)
        current_lines = 0
        MAX_FRAME_LINES = 20  # Conservative: leave room for title, padding

        def flush_frame(title: str, content: list[str]) -> str | None:
            if not content:
                return None
            inner = "\n\n".join(content)
            # If content already has \frametitle (from LLM), skip converter's title
            has_frametitle = any(
                c.strip().startswith(r"\frametitle{") for c in content
            )
            if has_frametitle:
                title_line = ""
            else:
                title_line = rf"\frametitle{{{title}}}" if title else ""
            parts: list[str] = [r"\begin{frame}"]
            if title_line:
                parts.append(f"  {title_line}")
            parts.append(inner)
            parts.append(r"\end{frame}")
            return "\n".join(parts)

        def estimate_block_lines(block: Block) -> int:
            """Estimate how many lines a block will take in Beamer."""
            if block.type == BlockType.FIGURE:
                return 18  # Figure takes most of the slide
            elif block.type == BlockType.TABLE:
                rows = len(block.lines) if block.lines else 5
                return min(rows + 5, 20)
            elif block.type == BlockType.FORMULA_DISPLAY:
                return block.content.count("\n") + 4
            elif block.type == BlockType.LIST_ITEM or block.type == BlockType.ENUM_ITEM:
                return block.content.count("\n") + 3
            elif block.type == BlockType.CODE_BLOCK:
                return block.content.count("\n") + 3
            elif block.type == BlockType.HEADING:
                return 2
            else:
                # Paragraph: estimate from text length
                text = block.content
                chars_per_line = 80
                raw_lines = text.count("\n") + 1
                char_lines = max(1, len(text) // chars_per_line)
                return max(raw_lines, char_lines) + 1

        i = 0
        while i < len(blocks):
            block = blocks[i]

            # Skip heading blocks (already handled as section titles)
            if block.type == BlockType.HEADING:
                i += 1
                continue

            block_lines = estimate_block_lines(block)

            # Large blocks: figures and tables always get their own frame
            if block.type in (BlockType.FIGURE, BlockType.TABLE):
                if current_frame:
                    f = flush_frame(current_title, current_frame)
                    if f:
                        frames.append(f)
                    current_frame = []
                    current_lines = 0

                frame_content = self._block_to_latex(block)
                f_title = self._escape_latex(block.caption or section_title)
                f = flush_frame(f_title, frame_content)
                if f:
                    frames.append(f)
                i += 1
                continue

            # If adding this block would overflow, start a new frame
            if current_lines + block_lines > MAX_FRAME_LINES and current_frame:
                f = flush_frame(current_title, current_frame)
                if f:
                    frames.append(f)
                current_frame = []
                current_lines = 0
                # Use section title for continuation frames
                current_title = self._escape_latex(section_title)

            current_frame.extend(self._block_to_latex(block))
            current_lines += block_lines
            i += 1

        # Flush remaining
        if current_frame:
            f = flush_frame(current_title, current_frame)
            if f:
                frames.append(f)

        return frames

    def _block_to_latex(self, block: Block) -> list[str]:
        if block.type == BlockType.PARAGRAPH:
            if block.is_latex:
                return [block.content]  # LLM-generated, already proper LaTeX
            return [self._escape_latex(block.content)]
        elif block.type == BlockType.FORMULA_DISPLAY:
            return [block.content]
        elif block.type == BlockType.HEADING:
            return []  # handled at section level
        elif block.type == BlockType.FIGURE:
            return self._figure_to_latex(block)
        elif block.type == BlockType.TABLE:
            return self._table_to_latex(block)
        elif block.type == BlockType.LIST_ITEM:
            return self._list_to_latex(block)
        elif block.type == BlockType.ENUM_ITEM:
            return self._enum_to_latex(block)
        elif block.type == BlockType.CODE_BLOCK:
            return [block.content]
        else:
            return [self._escape_latex(block.content)]

    def _figure_to_latex(self, block: Block) -> list[str]:
        self.figure_counter += 1
        caption = self._escape_latex(block.caption or f"Figure {self.figure_counter}")
        img_path = block.image_path or ""
        filename = Path(img_path).name if img_path else "figure.png"
        return [
            r"\begin{figure}",
            r"\centering",
            rf"\includegraphics[width=0.85\textwidth,height=0.55\textheight,keepaspectratio]{{{filename}}}",
            rf"\caption{{{caption}}}",
            r"\end{figure}",
        ]

    def _table_to_latex(self, block: Block) -> list[str]:
        self.table_counter += 1
        caption = self._escape_latex(block.caption or f"Table {self.table_counter}")

        lines = block.lines if block.lines else block.content.splitlines()
        if len(lines) < 2:
            return [self._escape_latex(block.content)]

        header = lines[0]
        col_count = header.count("|") - 1
        if col_count < 1:
            col_count = 1

        alignment = "|" + "c|" * col_count
        latex_lines = [r"\begin{table}",
                       r"\centering",
                       rf"\resizebox{{\textwidth}}{{!}}{{%",
                       rf"\begin{{tabular}}{{{alignment}}}",
                       r"\hline"]

        for i, line in enumerate(lines):
            if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
                latex_lines.append(r"\hline")
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            row = " & ".join(self._escape_latex(c) for c in cells)
            latex_lines.append(f"  {row} \\\\")
            if i == 0:
                latex_lines.append(r"\hline")

        latex_lines.append(r"\hline")
        latex_lines.append(r"\end{tabular}")
        latex_lines.append(r"}")
        latex_lines.append(rf"\caption{{{caption}}}")
        latex_lines.append(r"\end{table}")
        return latex_lines

    def _list_to_latex(self, block: Block) -> list[str]:
        items = block.content.splitlines()
        result = [r"\begin{itemize}"]
        for item in items:
            text = item.strip()
            if text.startswith("- "):
                text = text[2:]
            elif text.startswith("* "):
                text = text[2:]
            result.append(rf"  \item {self._escape_latex(text)}")
        result.append(r"\end{itemize}")
        return result

    def _enum_to_latex(self, block: Block) -> list[str]:
        items = block.content.splitlines()
        result = [r"\begin{enumerate}"]
        for item in items:
            text = re.sub(r"^\d+\.\s", "", item.strip())
            result.append(rf"  \item {self._escape_latex(text)}")
        result.append(r"\end{enumerate}")
        return result

    def _build_thanks_slide(self) -> str:
        return "\n".join([
            r"\begin{frame}{}",
            r"  \centering",
            r"  \Huge Thank you!",
            r"\end{frame}",
        ])

    @staticmethod
    def _escape_latex(text: str) -> str:
        """Escape special LaTeX characters, preserving math mode and LaTeX commands."""
        parts = re.split(r'(\$\$?.*?\$\$?)', text)
        result_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                result_parts.append(part)
            else:
                result_parts.append(BeamerConverter._escape_plain_text(part))
        return "".join(result_parts)

    @staticmethod
    def _escape_plain_text(text: str) -> str:
        """Escape LaTeX special chars in plain text (not math)."""
        result = text
        result = result.replace("\\", r"\textbackslash{}")
        result = result.replace("&", r"\&")
        result = result.replace("%", r"\%")
        result = result.replace("#", r"\#")
        result = result.replace("~", r"\textasciitilde{}")
        result = re.sub(r'(?<!\\)\^(\d+)', r'$^{\1}$', result)
        return result
