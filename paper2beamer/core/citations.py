"""Citation detection and .bib file generation."""

import re
from paper2beamer.core.models import Document, Citation


class CitationDetector:
    def extract(self, document: Document) -> tuple[list[Citation], str]:
        citations = document.citations
        bib_entries: list[str] = []

        ref_entries = self._parse_references_section(document.references_raw)

        for citation in citations:
            entry = self._build_bib_entry(citation, ref_entries)
            bib_entries.append(entry)

        bib_text = "\n\n".join(bib_entries)
        return citations, bib_text

    def _parse_references_section(self, references_raw: str) -> dict[str, dict]:
        entries: dict[str, dict] = {}
        if not references_raw:
            return entries

        ref_blocks = re.split(r'\n(?=\[)', references_raw)
        if len(ref_blocks) <= 1:
            ref_blocks = re.split(r'\n\n+', references_raw)

        for block in ref_blocks:
            block = block.strip()
            if not block:
                continue
            bracket_match = re.match(r'\[(\d+)\]\s*(.+)', block, re.DOTALL)
            if bracket_match:
                num = bracket_match.group(1)
                rest = bracket_match.group(2).strip()
                key = f"ref{num}"
                authors, title = self._parse_ref_entry(rest)
                entries[key] = {"authors": authors, "title": title, "raw": rest}
                continue
            key_match = re.match(r'([A-Z][a-z]+[\w]*)', block)
            if key_match:
                entries[key_match.group(1)] = {"raw": block}

        return entries

    def _parse_ref_entry(self, text: str) -> tuple[str, str]:
        parts = re.split(r'[.?!]\s+', text, maxsplit=2)
        authors = parts[0] if len(parts) > 0 else ""
        title = parts[1] if len(parts) > 1 else ""
        return authors, title

    def _build_bib_entry(self, citation: Citation,
                         ref_entries: dict[str, dict]) -> str:
        if citation.key in ref_entries:
            info = ref_entries[citation.key]
            authors = self._format_bib_authors(info.get("authors", ""))
            title = info.get("title", "").replace('"', "'")
            return (
                f"@misc{{{citation.key},\n"
                f"  author = {{{authors}}},\n"
                f"  title = {{{title}}},\n"
                f"  note = {{Extracted from paper}}\n"
                f"}}"
            )

        return (
            f"@misc{{{citation.key},\n"
            f"  note = {{Reference not found in paper text}}\n"
            f"}}"
        )

    def _format_bib_authors(self, authors_str: str) -> str:
        parts = [a.strip() for a in authors_str.split(",")]
        formatted = []
        for part in parts:
            names = part.split()
            if len(names) >= 2:
                formatted.append(f"{names[-1]}, {' '.join(names[:-1])}")
            else:
                formatted.append(part)
        return " and ".join(formatted)
