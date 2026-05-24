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
                parts.append(self._section_to_frames(section))
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

    def _section_to_frames(self, section: Section) -> str:
        frames: list[str] = []

        section_cmd = "section" if section.level == 1 else "subsection"
        frames.append(rf"\{section_cmd}{{{self._escape_latex(section.title)}}}")

        blocks = list(section.blocks)
        frame_content: list[str] = []
        frame_title = self._escape_latex(section.title)

        for i, block in enumerate(blocks):
            if block.type == BlockType.HEADING and block.heading_level == 2:
                if frame_content:
                    frames.append(self._make_frame(frame_title, frame_content))
                    frame_content = []
                frame_title = self._escape_latex(block.content)
                continue

            frame_content.extend(self._block_to_latex(block))

        if frame_content:
            frames.append(self._make_frame(frame_title, frame_content))

        for sub in section.subsections:
            frames.append(self._section_to_frames(sub))

        return "\n\n".join(frames)

    def _make_frame(self, title: str, content: list[str]) -> str:
        inner = "\n\n".join(content)
        title_cmd = rf"\frametitle{{{title}}}" if title else ""
        return "\n".join([
            r"\begin{frame}",
            f"  {title_cmd}" if title_cmd else "",
            inner,
            r"\end{frame}",
        ])

    def _block_to_latex(self, block: Block) -> list[str]:
        if block.type == BlockType.PARAGRAPH:
            return [self._escape_latex(block.content)]
        elif block.type == BlockType.FORMULA_DISPLAY:
            return [block.content]
        elif block.type == BlockType.HEADING:
            return []  # headings handled at section level
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
            rf"\includegraphics[width=\textwidth,height=0.65\textheight,keepaspectratio]{{{filename}}}",
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
