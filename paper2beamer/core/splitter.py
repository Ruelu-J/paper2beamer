"""Frame splitting — ensures Beamer content doesn't overflow slides."""

import re
from dataclasses import dataclass, field

MAX_LINES_PER_FRAME = 22
MAX_FORMULA_LINES = 16
MAX_TABLE_ROWS = 12
FRAME_TITLE_OVERHEAD = 2


@dataclass
class FrameSpec:
    title: str = ""
    content_parts: list[str] = field(default_factory=list)
    estimated_lines: int = FRAME_TITLE_OVERHEAD
    is_passthrough: bool = False  # if True, don't wrap in frame


class FrameSplitter:
    def __init__(
        self,
        max_lines: int = MAX_LINES_PER_FRAME,
        max_formula_lines: int = MAX_FORMULA_LINES,
        max_table_rows: int = MAX_TABLE_ROWS,
    ):
        self.max_lines = max_lines
        self.max_formula_lines = max_formula_lines
        self.max_table_rows = max_table_rows

    def split(self, tex_content: str) -> str:
        preamble, body, postamble = self._split_document(tex_content)

        frames = self._parse_frames(body)
        result_frames: list[FrameSpec] = []

        for frame in frames:
            result_frames.extend(self._split_frame(frame))

        body_result = self._assemble(result_frames)
        return preamble + "\n" + body_result + "\n" + postamble

    def _split_document(self, tex_content: str) -> tuple[str, str, str]:
        begin_doc = re.search(r'\\begin\{document\}', tex_content)
        end_doc = re.search(r'\\end\{document\}', tex_content)

        if not begin_doc:
            return "", tex_content, ""

        preamble = tex_content[:begin_doc.end()].strip()
        if end_doc:
            body = tex_content[begin_doc.end():end_doc.start()].strip()
            postamble = tex_content[end_doc.start():].strip()
        else:
            body = tex_content[begin_doc.end():].strip()
            postamble = ""

        return preamble, body, postamble

    def _parse_frames(self, tex_content: str) -> list[FrameSpec]:
        frames: list[FrameSpec] = []

        pattern = re.compile(
            r'\\begin\{frame\}\{?(.*?)\}?\n?(.*?)\\end\{frame\}',
            re.DOTALL,
        )
        pos = 0
        for match in pattern.finditer(tex_content):
            between = tex_content[pos:match.start()].strip()
            if between:
                frames.append(FrameSpec(
                    title="",
                    content_parts=[between],
                    estimated_lines=0,
                    is_passthrough=True,
                ))
            title = match.group(1).strip()
            body = match.group(2).strip()

            title = re.sub(r'\\frametitle\{([^}]*)\}', r'\1', title)
            title = re.sub(r'\\framesubtitle\{([^}]*)\}', r'', title)

            frames.append(FrameSpec(
                title=title,
                content_parts=[body],
                estimated_lines=self._estimate_lines(body) + FRAME_TITLE_OVERHEAD,
            ))
            pos = match.end()

        remaining = tex_content[pos:].strip()
        if remaining:
            frames.append(FrameSpec(
                title="",
                content_parts=[remaining],
                estimated_lines=0,
                is_passthrough=True,
            ))

        return frames

    def _split_frame(self, frame: FrameSpec) -> list[FrameSpec]:
        if frame.is_passthrough:
            return [frame]
        if frame.estimated_lines <= self.max_lines:
            return [frame]

        content = "\n\n".join(frame.content_parts)

        # Split at natural boundaries: paragraphs (double newlines)
        paragraphs = re.split(r'\n\s*\n', content)

        # If only one paragraph, check if it's a special block type
        if len(paragraphs) <= 1:
            return self._handle_oversized_single(frame.title, content)

        result: list[FrameSpec] = []
        current = FrameSpec(title=frame.title)
        overflow: list[str] = []  # paragraphs that don't fit in current frame

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_lines = self._estimate_lines(para)

            # If this paragraph alone overflows the max, it needs special handling
            if para_lines > self.max_lines:
                # Flush current frame first
                if current.content_parts:
                    result.append(current)
                    current = FrameSpec(title=frame.title)
                # Handle the oversized paragraph separately
                oversized = self._handle_oversized_single(frame.title, para)
                result.extend(oversized)
                continue

            # If adding this paragraph would overflow, start a new frame
            if current.estimated_lines + para_lines > self.max_lines:
                result.append(current)
                current = FrameSpec(
                    title=frame.title,
                    content_parts=[para],
                    estimated_lines=FRAME_TITLE_OVERHEAD + para_lines,
                )
            else:
                current.content_parts.append(para)
                current.estimated_lines += para_lines

        if current.content_parts:
            result.append(current)

        return result

    def _handle_oversized_single(
        self, title: str, content: str
    ) -> list[FrameSpec]:
        """Handle content that exceeds one frame even as a single block."""
        if r"\begin{table}" in content:
            return self._split_large_table(title, content)
        if r"\begin{equation" in content or "$$" in content or r"\begin{align" in content:
            return self._split_long_formula(title, content)
        if r"\includegraphics" in content:
            return [FrameSpec(
                title=title,
                content_parts=[content],
                estimated_lines=self.max_lines,
            )]
        if r"\begin{itemize}" in content or r"\begin{enumerate}" in content:
            return self._split_long_list(title, content)
        # For long paragraphs: use allowframebreaks as last resort
        return [FrameSpec(
            title=title,
            content_parts=[
                r"\begin{frame}[allowframebreaks]{" + title + "}\n"
                + content + "\n"
                + r"\end{frame}"
            ],
            estimated_lines=0,
        )]

    def _split_long_list(self, title: str, content: str) -> list[FrameSpec]:
        """Split a long itemize/enumerate across frames."""
        env_match = re.search(r'\\begin\{(itemize|enumerate)\}', content)
        if not env_match:
            return [FrameSpec(title=title, content_parts=[content],
                              estimated_lines=self.max_lines)]
        env_name = env_match.group(1)

        # Extract individual items
        items = re.findall(r'\\item\s+(.*?)(?=\\item\s+|\n*\\end\{' + env_name + r'\})',
                           content, re.DOTALL)
        if len(items) <= 1:
            return [FrameSpec(title=title, content_parts=[content],
                              estimated_lines=self.max_lines)]

        frames: list[FrameSpec] = []
        current_items: list[str] = []
        current_lines = FRAME_TITLE_OVERHEAD + 2  # begin/end env

        for item in items:
            item_text = item.strip()
            item_lines = item_text.count("\n") + 2  # \item + content
            if current_lines + item_lines > self.max_lines and current_items:
                frames.append(FrameSpec(
                    title=title,
                    content_parts=[
                        rf"\begin{{{env_name}}}"
                        + "\n" + "\n".join(current_items) + "\n"
                        + rf"\end{{{env_name}}}"
                    ],
                    estimated_lines=current_lines,
                ))
                current_items = []
                current_lines = FRAME_TITLE_OVERHEAD + 2
            current_items.append(rf"\item {item_text}")
            current_lines += item_lines

        if current_items:
            frames.append(FrameSpec(
                title=title,
                content_parts=[
                    rf"\begin{{{env_name}}}"
                    + "\n" + "\n".join(current_items) + "\n"
                    + rf"\end{{{env_name}}}"
                ],
                estimated_lines=current_lines,
            ))

        return frames

    def _split_large_table(
        self, title: str, content: str
    ) -> list[FrameSpec]:
        rows = content.splitlines()
        if len(rows) <= 1:
            return [FrameSpec(title=title, content_parts=[content],
                              estimated_lines=self.max_lines)]

        header_rows = []
        body_start = 0
        tabular_depth = 0
        for i, row in enumerate(rows):
            if r"\begin{tabular}" in row:
                tabular_depth += 1
            if r"\end{tabular}" in row:
                tabular_depth -= 1
            if r"\hline" in row and tabular_depth == 1:
                if not header_rows:
                    header_rows = rows[: i + 1]
                    body_start = i + 1
                elif i > body_start:
                    break

        if not header_rows:
            header_rows = [rows[0]]

        data_rows = rows[body_start:]
        data_rows = [
            r for r in data_rows
            if r.strip() and not r.strip().startswith(r"\end{tabular}")
            and not r.strip().startswith(r"\end{table}")
            and r.strip() != r"\hline"
        ]

        frames: list[FrameSpec] = []
        chunk_size = self.max_table_rows

        for chunk_start in range(0, len(data_rows), chunk_size):
            chunk = data_rows[chunk_start:chunk_start + chunk_size]
            chunk_title = title
            if chunk_start > 0:
                chunk_title += " (continued)"

            table_lines = [
                r"\begin{table}",
                r"\centering",
                r"\resizebox{\textwidth}{!}{%",
                header_rows[0],
                *header_rows[1:],
                *chunk,
                r"\hline",
                r"\end{tabular}",
                r"}",
                r"\end{table}",
            ]

            frames.append(FrameSpec(
                title=chunk_title,
                content_parts=["\n".join(table_lines)],
                estimated_lines=len(chunk) + len(header_rows) + 4,
            ))

        return frames

    def _split_long_formula(
        self, title: str, content: str
    ) -> list[FrameSpec]:
        if r"\begin{aligned}" in content or r"\begin{align" in content:
            body_match = re.search(
                r'\\begin\{(?:aligned|align\*?)\}(.+?)\\end\{(?:aligned|align\*?)\}',
                content, re.DOTALL,
            )
            if body_match:
                inner = body_match.group(1)
                lines = [l.strip() for l in inner.split(r"\\") if l.strip()]
                if len(lines) <= self.max_formula_lines:
                    return [FrameSpec(
                        title=title,
                        content_parts=[content],
                        estimated_lines=len(lines) + 4,
                    )]

                env_match = re.search(
                    r'\\begin\{(aligned|align\*?)\}', content
                )
                env_name = env_match.group(1) if env_match else "aligned"
                frames: list[FrameSpec] = []
                for chunk_start in range(0, len(lines), self.max_formula_lines):
                    chunk = lines[chunk_start:chunk_start + self.max_formula_lines]
                    chunk_title = title
                    if chunk_start > 0:
                        chunk_title += " (continued)"
                    formula = (
                        rf"\begin{{{env_name}}}"
                        + r" \\ ".join(chunk)
                        + rf"\end{{{env_name}}}"
                    )
                    frames.append(FrameSpec(
                        title=chunk_title,
                        content_parts=[formula],
                        estimated_lines=len(chunk) + 2,
                    ))
                return frames

        return [FrameSpec(
            title=title,
            content_parts=[content],
            estimated_lines=20,
        )]

    def _assemble(self, frames: list[FrameSpec]) -> str:
        parts: list[str] = []
        for frame in frames:
            if not frame.content_parts:
                continue
            combined = "\n\n".join(frame.content_parts)
            if frame.is_passthrough or combined.startswith(r"\begin{frame}"):
                parts.append(combined)
            else:
                title = self._escape_frame_title(frame.title)
                parts.append(r"\begin{frame}{" + title + "}")
                parts.append(combined)
                parts.append(r"\end{frame}")
        return "\n\n".join(parts)

    def _estimate_lines(self, content: str) -> int:
        if not content.strip():
            return 0
        if r"\begin{table}" in content:
            return content.count(r"\\") + 8
        if r"\begin{equation" in content or "$$" in content or r"\begin{align" in content:
            return content.count("\n") + 3
        if r"\begin{itemize}" in content or r"\begin{enumerate}" in content:
            return content.count(r"\item") + 4
        if r"\includegraphics" in content:
            return 16
        if r"\section{" in content or r"\subsection{" in content:
            return 3
        lines = content.count("\n") + 1
        chars_per_line = 80
        for paragraph in content.splitlines():
            para_lines = max(1, len(paragraph) // chars_per_line)
            lines += para_lines - 1
        return lines

    @staticmethod
    def _escape_frame_title(title: str) -> str:
        return title.replace("\\", "").replace("{", "").replace("}", "")
