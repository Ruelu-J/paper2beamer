"""LLM-based Beamer converter — understands templates and generates LaTeX.

Unlike the programmatic BeamerConverter, this sends the template structure
and paper content to an LLM, which generates properly styled Beamer LaTeX
that follows the template's patterns (colors, fonts, frame styles, etc.).

Key design: the template preamble is used AS-IS (programmatically updated with
paper title/author/institute/date). The LLM only generates frame content for
the body. This guarantees the template's styling is never lost.
"""

import asyncio
import json
import re
from pathlib import Path

from paper2beamer.config import settings
from paper2beamer.core.models import Document, OutputMode, BlockType


class LLMBeamerConverter:
    """Uses LLM to generate Beamer LaTeX that follows a specific template."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
    ):
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def convert(
        self,
        document: Document,
        template_dir: str | Path,
        output_mode: OutputMode,
    ) -> str:
        """Generate complete Beamer LaTeX using the template and paper content."""
        template_dir = Path(template_dir)

        # Read template
        template_preamble, template_body, template_post = \
            self._read_template(template_dir)

        # Build correct preamble from template (programmatic, no LLM involved)
        preamble = self._build_preamble(template_preamble, document)

        # For full mode: always batch by blocks to avoid LLM hallucination
        if output_mode == OutputMode.FULL:
            main_sections = self._filter_sections(document.sections)
            body = await self._convert_batched_body(
                document, template_body, output_mode,
            )
        else:
            body = await self._convert_body(
                document, template_body, output_mode,
            )

        # Assemble: preamble + body + post
        post = template_post if template_post else r"\end{document}"
        if r"\end{document}" not in body:
            body = body + "\n" + post
        if body.startswith(r"\begin{document}"):
            body = body[len(r"\begin{document}"):]

        beamer_tex = preamble + "\n" + r"\begin{document}" + "\n" + body

        # Validate and fix — LLM checks its own output for compile errors
        if self.enabled:
            beamer_tex = await self._validate_and_fix(beamer_tex, template_body)

        return beamer_tex

    # ------------------------------------------------------------------
    # Validation (programmatic precheck + LLM fix)
    # ------------------------------------------------------------------

    @staticmethod
    def _precheck(tex: str) -> list[str]:
        """Quick programmatic check for LaTeX issues. Returns list of problems."""
        problems = []

        # 1. Check \end{document} exists
        if r'\end{document}' not in tex:
            problems.append("missing \\end{document}")

        # 1a. Universal \begin{}/\end{} pairing check (covers ALL envs:
        # frame, enumerate, itemize, equation, theorem, proof, block,
        # columns, tikzpicture, tabular, ...). This is the single source
        # of truth — no whitelist.
        env_problems = LLMBeamerConverter._validate_env_pairs(tex)
        for p in env_problems[:20]:  # cap to avoid noise
            if p['kind'] == 'unclosed':
                problems.append(
                    f"\\begin{{{p['env']}}} at line {p['line']} "
                    f"has no matching \\end{{{p['env']}}}"
                )
            elif p['kind'] == 'unclosed_inner':
                problems.append(
                    f"\\begin{{{p['env']}}} at line {p['line']} "
                    f"closed out of order (inner env not closed first)"
                )
            elif p['kind'] == 'orphan_end':
                problems.append(
                    f"orphan \\end{{{p['env']}}} at line {p['line']} "
                    f"(no matching \\begin)"
                )

        # 2. Smart brace balance (skip escaped \{ \} \% \& \_ \#)
        depth = 0
        i = 0
        while i < len(tex):
            ch = tex[i]
            if ch == '\\' and i + 1 < len(tex):
                next_ch = tex[i + 1]
                if next_ch in '{}\\&%#_':
                    i += 2  # skip escape + char
                    continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            if depth < 0:
                problems.append(f"extra '}}' at position {i}")
                # reset depth to continue checking
                depth = 0
            i += 1
        if depth != 0:
            problems.append(f"unbalanced braces: {depth} unmatched '{{'")

        # 3. Check for fragile commands in moving arguments
        # \cmd{X} (with brace args) in frame/section titles cause
        # "File ended while scanning use of \@writefile" errors
        import re as _re
        fragile_patterns = [
            r'\\mathcal\{[^}]*\}',
            r'\\mathbf\{[^}]*\}',
            r'\\mathbb\{[^}]*\}',
            r'\\mathit\{[^}]*\}',
            r'\\mathrm\{[^}]*\}',
            r'\\mathsf\{[^}]*\}',
            r'\\mathtt\{[^}]*\}',
            r'\\widehat\{[^}]*\}',
            r'\\widetilde\{[^}]*\}',
            r'\\textbf\{[^}]*\}',
            r'\\textit\{[^}]*\}',
            r'\\text\{[^}]*\}',
        ]
        fragile_re = '|'.join(fragile_patterns)

        # Check frame titles
        for m in _re.finditer(r'\\begin\{frame\}\{', tex):
            title_start = m.end()
            depth = 1
            j = title_start
            while j < len(tex) and depth > 0:
                if tex[j] == '\\' and j + 1 < len(tex):
                    if tex[j + 1] in '{}':
                        j += 2
                        continue
                if tex[j] == '{':
                    depth += 1
                elif tex[j] == '}':
                    depth -= 1
                j += 1
            title_text = tex[title_start:j - 1]
            fragile = _re.findall(fragile_re, title_text)
            if fragile:
                problems.append(
                    f"fragile cmd in frame title: {', '.join(fragile[:3])}"
                )

        # Check \section/\subsection titles (moving arguments)
        section_found = _re.findall(fragile_re, tex)
        # Only flag if they appear near \section or \subsection
        for m in _re.finditer(
            r'\\(?:section|subsection|subsubsection)\{', tex,
        ):
            title_start = m.end()
            depth = 1
            j = title_start
            while j < len(tex) and depth > 0:
                if tex[j] == '\\' and j + 1 < len(tex):
                    if tex[j + 1] in '{}':
                        j += 2
                        continue
                if tex[j] == '{':
                    depth += 1
                elif tex[j] == '}':
                    depth -= 1
                j += 1
            title_text = tex[title_start:j - 1]
            fragile = _re.findall(fragile_re, title_text)
            if fragile:
                problems.append(
                    f"fragile cmd in section title: {', '.join(fragile[:3])}"
                )
                break

        return problems

    async def _validate_and_fix(
        self,
        beamer_tex: str,
        template_body: str,
    ) -> str:
        """Validate and fix LaTeX compilation issues.
        1. Programmatic precheck → fix known patterns
        2. LLM title review → check PDF bookmark / HyPL@Entry issues
        """
        # Phase 1: programmatic precheck + fix
        problems = self._precheck(beamer_tex)
        if problems:
            print(f"  Validation: {len(problems)} precheck issue(s), "
                  f"applying programmatic fixes", flush=True)
            beamer_tex = self._apply_programmatic_fixes(beamer_tex, problems)
            # Re-check
            problems = self._precheck(beamer_tex)
            if problems:
                print(f"  Validation: {len(problems)} issue(s) remain "
                      f"after fix", flush=True)

        # Phase 2: LLM review of moving arguments (section/frame titles)
        # This catches HyPL@Entry and other PDF bookmark issues
        beamer_tex = await self._llm_review_titles(beamer_tex, template_body)

        return beamer_tex

    @staticmethod
    def _apply_programmatic_fixes(tex: str, problems: list[str]) -> str:
        """Apply programmatic fixes based on detected problems."""
        # Re-run _fix_title_braces and _fix_llm_errors which handle
        # fragile commands, \&, and brace issues in titles
        return LLMBeamerConverter._fix_title_braces(tex)

    async def _llm_review_titles(
        self,
        beamer_tex: str,
        template_body: str,
    ) -> str:
        """Send section/frame titles to LLM for HyPL@Entry / PDF bookmark
        review. Only the titles are sent (not full .tex), so this is fast."""
        import re as _re

        # Extract all moving-argument titles
        titles: list[str] = []
        for cmd in [r'\section', r'\subsection', r'\subsubsection',
                     r'\begin{frame}']:
            for m in _re.finditer(_re.escape(cmd) + r'\{', beamer_tex):
                start = m.end()
                depth = 1
                j = start
                while j < len(beamer_tex) and depth > 0:
                    if beamer_tex[j] == '\\' and j + 1 < len(beamer_tex):
                        if beamer_tex[j + 1] in '{}':
                            j += 2
                            continue
                    if beamer_tex[j] == '{':
                        depth += 1
                    elif beamer_tex[j] == '}':
                        depth -= 1
                    j += 1
                title = beamer_tex[start:j - 1]
                # Skip empty titles and titlepage
                if title.strip() and title.strip() != r'\titlepage':
                    titles.append(f"{cmd}: {title}")

        if not titles:
            return beamer_tex

        titles_text = '\n'.join(titles[:80])  # Cap at 80 titles
        body_excerpt = (
            template_body[:1500] if len(template_body) > 1500
            else template_body
        )

        prompt = (
            "You are a LaTeX / Beamer compilation expert. Review the "
            "section and frame titles below for issues that would cause "
            "compilation errors with xelatex + hyperref.\n\n"
            "Focus on:\n"
            "- Fragile commands (\\cmd{X}) that break PDF bookmarks "
            "(cause \\HyPL@Entry errors)\n"
            "- Special characters (& % # _) that need escaping in "
            "moving arguments\n"
            "- Unbalanced { } braces\n"
            "- Commands that \\pdfstringdef cannot convert\n\n"
            "TEMPLATE STYLE (for reference):\n"
            f"```latex\n{body_excerpt if body_excerpt else '% Standard'}\n```\n\n"
            "TITLES TO REVIEW:\n"
            f"{titles_text}\n\n"
            "If ALL titles are safe, reply ONLY with: ALL CLEAN\n"
            "If any title has issues, reply with the PROBLEMATIC titles "
            "and the EXACT fix needed (one per line), format:\n"
            "  FIX: <original> → <fixed>\n"
            "Do NOT output the full .tex file."
        )

        response = await self._call_llm(prompt, max_tokens=2048)
        response = response.strip()

        if 'ALL CLEAN' in response.upper():
            return beamer_tex

        # Apply fixes from LLM response
        import re as _re2
        fixes = _re2.findall(
            r'FIX:\s*(.+?)\s*→\s*(.+?)(?:\n|$)',
            response,
        )
        if not fixes:
            return beamer_tex

        print(f"  Validation: applying {len(fixes)} LLM-suggested fixes",
              flush=True)
        for original, fixed in fixes:
            original = original.strip()
            fixed = fixed.strip()
            if original and original in beamer_tex:
                beamer_tex = beamer_tex.replace(original, fixed)
                print(f"    Fixed: {original[:60]} → {fixed[:60]}",
                      flush=True)

        return beamer_tex

    # ------------------------------------------------------------------
    # Compile → fix → recompile loop
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_compile_errors(log_text: str) -> list[dict]:
        """Extract real LaTeX errors (not warnings) from compile log.
        Returns list of {error, line_num, context, source_excerpt}.

        For each `! ...` block we walk forward up to 30 lines looking for
        `l.NNN <source>` — that line carries the *exact* source text TeX
        was reading when it choked, which is far more useful for the LLM
        than our own line-based slice from .tex. We also capture the
        next line (TeX prints the continuation there) and any
        'Runaway argument?' diagnostic that may follow."""
        import re as _re
        errors: list[dict] = []
        lines = log_text.split('\n')

        for i, line in enumerate(lines):
            if not line.startswith('!'):
                continue
            error_text = line[1:].strip()

            # Skip non-error ! lines:
            # - Empty ! lines (just "!")
            # - Emergency stop / No pages (consequences, not causes)
            # - Package version mismatch warnings
            if not error_text:
                continue
            if any(skip in error_text for skip in
                   ['Emergency stop', 'No pages',
                    'LaTeX Error: Missing \\begin']):
                continue

            # Hunt for line number AND source excerpt within 30 lines.
            # The TeX log format is:
            #     l.<N> <source up to the error point>
            #           <continuation after the error point>
            line_num = 0
            source_excerpt = ''
            runaway = ''
            for j in range(i, min(i + 30, len(lines))):
                if not runaway and 'Runaway argument' in lines[j]:
                    runaway = lines[j].strip()
                if line_num == 0:
                    m = _re.match(r'l\.(\d+)\s?(.*)', lines[j].lstrip())
                    if m:
                        line_num = int(m.group(1))
                        head = m.group(2)
                        tail = (lines[j + 1].strip()
                                if j + 1 < len(lines) else '')
                        source_excerpt = (head + ' / ' + tail).strip(' /')
                        if not source_excerpt:
                            source_excerpt = head or tail

            # Get short context (line right after the !)
            context = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if runaway:
                context = (runaway + ' || ' + context)[:300]

            errors.append({
                'error': error_text[:240],
                'line_num': line_num,
                'context': context[:300],
                'source_excerpt': source_excerpt[:300],
            })

        # Deduplicate by line_num + error prefix
        seen = set()
        unique = []
        for e in errors:
            key = (e['line_num'], e['error'][:60])
            if key not in seen:
                seen.add(key)
                unique.append(e)

        # Return ALL unique errors (no arbitrary cap)
        return unique

    @staticmethod
    def _extract_error_snippets(
        beamer_tex: str, errors: list[dict], context_lines: int = 8,
    ) -> str:
        """Extract code snippets around error locations from the .tex file."""
        tex_lines = beamer_tex.split('\n')
        snippets = []
        for e in errors:
            ln = e['line_num']
            if ln <= 0:
                snippets.append(f"ERROR: {e['error']}\n  (line unknown)")
                continue
            start = max(0, ln - context_lines - 1)
            end = min(len(tex_lines), ln + context_lines)
            code = '\n'.join(
                f"{i+1}: {tex_lines[i]}"
                for i in range(start, end)
            )
            snippets.append(
                f"### Error at line {ln}: {e['error']}\n"
                f"```latex\n{code}\n```"
            )
        return '\n\n'.join(snippets)

    @staticmethod
    def _extract_error_frames(
        beamer_tex: str, errors: list[dict],
    ) -> str:
        """For each error, extract the ENTIRE surrounding frame, so the
        LLM has full context to fix brace issues. For line-0 errors, send
        the last few frames of the document."""
        tex_lines = beamer_tex.split('\n')
        frame_starts = []
        frame_ends = []
        for i, line in enumerate(tex_lines):
            if '\\begin{frame}' in line:
                frame_starts.append(i)
            if '\\end{frame}' in line:
                frame_ends.append(i)

        seen_frames = set()
        snippets = []
        for e in errors[:10]:
            ln = e['line_num'] - 1  # 0-based
            if ln < 0:
                # Error at line 0: likely a brace/EOF issue — send
                # the last 3 frames of the document
                if 'eof_frames' not in seen_frames:
                    seen_frames.add('eof_frames')
                    last_frames = []
                    for s, en in zip(frame_starts[-3:], frame_ends[-3:]):
                        code = '\n'.join(
                            f"{i+1}: {tex_lines[i]}"
                            for i in range(max(0, s - 1), min(len(tex_lines), en + 2))
                        )
                        last_frames.append(code)
                    snippets.append(
                        "### Error at EOF: file ended while scanning — "
                        "check the LAST frame(s) for missing }} or "
                        "\\end{{frame}}\n"
                        "```latex\n" + '\n\n'.join(last_frames) + "\n```"
                    )
                continue

            # Find enclosing frame
            f_start = 0
            f_end = len(tex_lines) - 1
            for s, en in zip(frame_starts, frame_ends):
                if s <= ln <= en:
                    f_start = s
                    f_end = en
                    break
            if (f_start, f_end) in seen_frames:
                continue
            seen_frames.add((f_start, f_end))

            code = '\n'.join(
                f"{i+1}: {tex_lines[i]}"
                for i in range(max(0, f_start - 1), min(len(tex_lines), f_end + 2))
            )
            snippets.append(
                f"### Error at line {e['line_num']}: {e['error']}\n"
                f"```latex\n{code}\n```"
            )
        return '\n\n'.join(snippets)

    async def _llm_fix_compile_errors(
        self,
        beamer_tex: str,
        errors: list[dict],
        template_body: str,
    ) -> str:
        """Ask LLM to fix compile errors. Sends only the problematic frames
        (not the full .tex), ensuring the LLM has full frame context for
        brace fixes but can't hallucinate/modify other content."""
        frames_text = self._extract_error_frames(beamer_tex, errors)

        # Pull the source excerpts straight from the TeX log so the LLM
        # sees the exact token TeX choked on (especially for "Missing $
        # inserted" / "Undefined control sequence" where the error
        # message alone is not actionable).
        excerpt_block = '\n'.join(
            f"- line {e.get('line_num', '?')}: {e['error']} "
            f"|| TeX-saw: {e.get('source_excerpt', '') or '(no l.NN in log)'}"
            f"{(' || ' + e['context']) if e.get('context') else ''}"
            for e in errors[:10]
        )

        prompt = (
            "You are a LaTeX debugging expert. Fix ALL the errors in the "
            "Beamer frames below.\n\n"
            "## ERRORS (with TeX source context)\n"
            f"{excerpt_block}\n\n"
            "## FRAME CODE\n"
            f"{frames_text}\n\n"
            "## FIX INSTRUCTIONS\n"
            "For each frame, output the CORRECTED version in this format:\n"
            "```latex\n"
            "FRAME <N>: <original title>\n"
            "<corrected frame content>\n"
            "```\n\n"
            "Fix patterns:\n"
            "- 'Missing $ inserted' → wrap math symbols (^ _ \\frac etc.) "
            "in $...$ or move to an equation environment\n"
            "- 'Undefined control sequence' → remove the command or "
            "replace with a standard one\n"
            "- 'File ended while scanning' → close a missing }} or "
            "\\end{frame}\n"
            "- \\tag in equation*/$$ → remove \\tag or use \\begin{equation}\n"
            "- Brace imbalance → find and fix missing { or }\n"
            "- figs/ path → images/\n"
            "- NEVER summarize or omit content — fix ONLY the errors\n\n"
            "Output corrected frames in ```latex FRAME blocks:"
        )

        response = await self._call_llm(prompt, max_tokens=8192)

        # Parse frame fixes from response
        import re as _re
        frame_fixes = _re.findall(
            r'FRAME\s+(\d+):\s*(.+?)\n```latex\n(.+?)```',
            response, _re.DOTALL,
        )

        if not frame_fixes:
            return beamer_tex

        # Apply fixes by matching frame content
        tex_lines = beamer_tex.split('\n')
        fixed_count = 0
        for fix in frame_fixes:
            frame_title = fix[1].strip()
            new_content = fix[2].strip()
            for i, line in enumerate(tex_lines):
                if '\\begin{frame}{' in line and frame_title[:30] in line:
                    depth = 1
                    j = i + 1
                    while j < len(tex_lines) and depth > 0:
                        if '\\begin{frame}' in tex_lines[j]:
                            depth += 1
                        if '\\end{frame}' in tex_lines[j]:
                            depth -= 1
                        j += 1
                    replace_lines = new_content.split('\n')
                    tex_lines[i:j] = replace_lines
                    fixed_count += 1
                    break

        result = '\n'.join(tex_lines)

        # Always re-apply programmatic fixes to the result
        parts = result.split('\\begin{document}', 1)
        if len(parts) == 2:
            result = parts[0] + '\\begin{document}' + \
                LLMBeamerConverter._fix_llm_errors(parts[1])
        else:
            result = LLMBeamerConverter._fix_llm_errors(result)

        if fixed_count > 0:
            print(f"    Replaced {fixed_count} frame(s)", flush=True)

        return result

    async def compile_and_fix(
        self,
        beamer_tex: str,
        compile_func,
        template_body: str,
        max_attempts: int = 5,
    ) -> tuple[str, bytes | None, str]:
        """Compile → check errors → LLM fix → recompile (up to N attempts).
        Returns (final_tex, pdf_bytes, log_text).

        After each LLM repair we re-run the deterministic structural fixer
        (\\begin/\\end pairing + brace title sanitization) so any new
        unbalanced environments introduced by the LLM are caught before the
        next latexmk run. We never silently bail on errors — only when
        latexmk succeeds OR the attempt budget is exhausted."""
        pdf_bytes = None
        log_text = ""
        beamer_tex = self._fix_llm_errors(beamer_tex)

        for attempt in range(max_attempts):
            print(f"  Compile attempt {attempt + 1}/{max_attempts}...",
                  flush=True)
            pdf_bytes, log_text = await compile_func(beamer_tex)

            errors = self._extract_compile_errors(log_text)
            env_issues = self._validate_env_pairs(beamer_tex)

            if not errors and pdf_bytes and not env_issues:
                print(f"  Compilation successful! "
                      f"({len(pdf_bytes):,} bytes PDF)", flush=True)
                return beamer_tex, pdf_bytes, log_text

            if errors:
                print(f"  Found {len(errors)} compile error(s), "
                      f"asking LLM to fix...", flush=True)
                for e in errors[:5]:
                    print(f"    - line {e.get('line_num', '?')}: "
                          f"{e['error'][:100]}", flush=True)
            elif env_issues:
                print(f"  Structural \\begin/\\end imbalance "
                      f"({len(env_issues)} issue(s)) — asking LLM",
                      flush=True)
                # Convert env_issues into pseudo-errors so the same
                # repair prompt can be reused.
                errors = [
                    {
                        'error': (
                            f"environment {p['env']} not properly "
                            f"closed ({p['kind']})"
                        ),
                        'line_num': p['line'],
                        'context': '',
                    }
                    for p in env_issues[:10]
                ]
            else:
                # No errors found but no PDF: likely a non-zero exit
                # without an "!" line (e.g. fontspec or missing image).
                # Send the tail of the log to the LLM.
                tail = log_text[-3000:]
                errors = [{
                    'error': 'latexmk exited without producing PDF; '
                             'see log tail',
                    'line_num': 0,
                    'context': tail[:300],
                }]
                print("  No '!' errors found but PDF missing — sending "
                      "log tail to LLM", flush=True)

            if attempt == max_attempts - 1:
                break

            prev_tex = beamer_tex
            beamer_tex = await self._llm_fix_compile_errors(
                beamer_tex, errors, template_body,
            )
            # Re-run the deterministic structural fixer after every LLM
            # edit — this catches any new \\begin without \\end the LLM
            # introduced and rebalances them before the next latexmk pass.
            beamer_tex = self._fix_llm_errors(beamer_tex)

            # Stagnation: LLM produced an identical (or trivially
            # different) .tex. Continuing would just rerun the same
            # latexmk → same error. Bail out and let the user inspect.
            if beamer_tex == prev_tex:
                print(
                    "  LLM produced no change — stopping early "
                    "(error is not actionable from the log alone)",
                    flush=True,
                )
                break

        return beamer_tex, pdf_bytes, log_text

    # ------------------------------------------------------------------

    @staticmethod
    def _build_preamble(template_preamble: str, document: Document) -> str:
        """Update template preamble with paper metadata, keeping everything else."""
        preamble = template_preamble
        authors_str = ", ".join(document.authors) if document.authors else "Unknown"

        authors_escaped = _escape_tex(authors_str)
        # Replace non-ASCII chars AFTER _escape_tex (to avoid \ being mangled)
        for char, latex_cmd in [
            ('Ü', r'\"U'), ('ü', r'\"u'),
            ('ö', r'\"o'), ('ä', r'\"a'),
            ('ß', r'\ss{}'),
        ]:
            authors_escaped = authors_escaped.replace(char, latex_cmd)

        preamble = re.sub(
            r'\\title\{[^}]*\}',
            lambda m: '\\title{' + _escape_tex(document.title) + '}',
            preamble,
            count=1,
        )
        preamble = re.sub(
            r'\\author\{[^}]*\}',
            lambda m: '\\author{' + authors_escaped + '}',
            preamble,
            count=1,
        )
        preamble = re.sub(
            r'\\institute\{[^}]*\}',
            lambda m: '\\institute{' + authors_escaped + '}',
            preamble,
            count=1,
        )
        preamble = re.sub(
            r'\\date\{[^}]*\}',
            lambda m: r'\date{\today}',
            preamble,
            count=1,
        )
        preamble = re.sub(
            r'\\subtitle\{[^}]*\}\s*',
            '',
            preamble,
        )

        # Override footline: remove author/institute from every slide bottom
        preamble += (
            '\n\\setbeamertemplate{footline}{'
            '\\hfill\\insertframenumber/\\inserttotalframenumber\\hfill}'
        )

        return preamble.strip()

    # ------------------------------------------------------------------
    # Body generation (LLM generates frames only)
    # ------------------------------------------------------------------

    async def _convert_body(
        self,
        document: Document,
        template_body: str,
        output_mode: OutputMode,
    ) -> str:
        """Generate body frames via LLM (no preamble, no documentclass)."""
        paper_content = self._format_document(document, output_mode)
        if output_mode == OutputMode.ABSTRACT:
            prompt = self._build_abstract_prompt(template_body, paper_content)
        else:
            prompt = self._build_body_prompt(template_body, paper_content, output_mode)
        response = await self._call_llm(prompt)
        body = self._extract_body(response)
        return self._fix_llm_errors(body)

    async def _convert_batched_body(
        self,
        document: Document,
        template_body: str,
        output_mode: OutputMode,
    ) -> str:
        """Generate body frames in batches — one chunk of blocks per LLM call."""
        main_sections = self._filter_sections(document.sections)

        if not main_sections:
            return await self._convert_body(document, template_body, output_mode)

        body_excerpt = template_body[:4000] if len(template_body) > 4000 else template_body

        # Flatten all blocks across all sections (preserving section boundaries)
        all_items: list = []
        for section in main_sections:
            all_items.append((section.title, section.level, None))  # section marker
            for block in section.blocks:
                all_items.append((section.title, section.level, block))
            for sub in section.subsections:
                all_items.append((sub.title, sub.level, None))  # subsection marker
                for block in sub.blocks:
                    all_items.append((sub.title, sub.level, block))

        MAX_BLOCKS = 50  # blocks per LLM call (fewer calls = less overhead)

        # Chunk the items, respecting that markers should stay with their blocks
        chunks = self._chunk_items(all_items, MAX_BLOCKS)

        # Map level → LaTeX section command so the LLM never has to
        # guess the hierarchy from the heading text alone.
        _LEVEL_CMD = {1: r'\section', 2: r'\subsection', 3: r'\subsubsection'}

        def _section_cmd(level: int) -> str:
            return _LEVEL_CMD.get(level, r'\subsubsection')

        def _heading_only(title: str) -> str:
            """Strip leading '1.2. ' numbering from heading title, leaving
            only the human-readable name (the LaTeX cmd carries the level)."""
            return re.sub(r'^[\d]+(?:\.[\d]+)*\.?\s+', '', title).strip()

        def _build_chunk_content(chunk):
            lines = []
            for section_title, section_level, block in chunk:
                if block is None:
                    # Emit an explicit instruction: which LaTeX command to
                    # use AND the clean title. The LLM must copy this exactly.
                    cmd = _section_cmd(section_level)
                    clean = _heading_only(section_title)
                    indent = '  ' * (section_level - 1)
                    lines.append(
                        f"\n{indent}[USE {cmd}{{{clean}}}]"
                    )
                else:
                    blk_text = self._format_block(block)
                    if blk_text:
                        lines.append(blk_text)
            return "\n".join(lines)

        # Batch 1: title + TOC + first chunk (must run first)
        first_chunk = chunks[0]
        first_content = (
            f"TITLE: {document.title}\n"
            f"AUTHORS: {', '.join(document.authors)}\n"
            f"ABSTRACT: {document.abstract[:2000] if document.abstract else 'N/A'}\n\n"
            f"## CONTENT TO CONVERT\n{_build_chunk_content(first_chunk)}"
        )
        first_prompt = self._build_body_prompt(
            template_body, first_content, output_mode,
        )
        first_response = await self._call_llm(first_prompt)
        body = self._extract_body(first_response) or ""

        # Batches 2..N: run in PARALLEL (they are independent of each other)
        remaining_chunks = chunks[1:]
        if remaining_chunks:
            # Use smaller template excerpt for continuation batches
            _body_short = body_excerpt[:2000] if len(body_excerpt) > 2000 else body_excerpt

            async def _process_chunk(chunk):
                chunk_content = _build_chunk_content(chunk)
                prompt = (
                    f"Continue a Beamer presentation. Convert ALL content into frames.\n\n"
                    f"Style:\n```latex\n{_body_short if _body_short else '% Standard'}\n```\n\n"
                    f"Content:\n{chunk_content}\n\n"
                    f"Rules:\n"
                    f"- English only. NEVER translate.\n"
                    f"- EVERY \\begin{{frame}} MUST have \\end{{frame}}\n"
                    f"- Do NOT generate title slide, TOC, or \\end{{document}}\n"
                    f"- [USE \\section/\\subsection/\\subsubsection{{X}}]: emit EXACTLY that command, "
                    f"never change the level\n"
                    f"- Convert EVERY [TEXT]/[FORMULA]/[TABLE]/[ITEM]/[ENUM]\n"
                    f"- Keep ALL \\cite{{...}} references\n"
                    f"- \\begin{{frame}}{{Title}} format, plain text titles\n"
                    f"- Output ONLY ```latex ... ``` block"
                )
                response = await self._call_llm(prompt)
                return self._extract_body(response) or ""

            # Fire all remaining chunks concurrently
            tasks = [_process_chunk(c) for c in remaining_chunks]
            results = await asyncio.gather(*tasks)
            for chunk_tex in results:
                if chunk_tex:
                    body += "\n" + chunk_tex

        # No separate final batch — the last content chunk already ends
        # the presentation naturally. \end{document} is appended by _convert().
        return self._fix_llm_errors(body)

    @staticmethod
    def _chunk_items(
        items: list,
        max_blocks: int,
    ) -> list[list]:
        """Split items into chunks of at most max_blocks actual blocks each."""
        chunks = []
        current: list[tuple[str | None, int, object]] = []
        block_count = 0

        for item in items:
            _, _, block = item
            is_marker = (block is None)

            if not is_marker:
                block_count += 1

            current.append(item)

            if block_count >= max_blocks:
                chunks.append(current)
                current = []
                block_count = 0

        if current:
            chunks.append(current)

        return chunks

    def _build_body_prompt(
        self,
        template_body: str,
        paper_content: str,
        output_mode: OutputMode,
    ) -> str:
        """Build prompt asking LLM to generate ONLY body frames."""
        body_excerpt = template_body[:4000] if len(template_body) > 4000 else template_body
        max_content = 60000
        paper_excerpt = paper_content[:max_content] if len(paper_content) > max_content else paper_content

        return f"""You are a LaTeX Beamer typesetter. Convert the paper content below into Beamer frames. Output ONLY body LaTeX in ```latex ``` block.

Language: English only. Do NOT translate.

Style reference (follow frame structure, colors, block styling):
```latex
{body_excerpt if body_excerpt else '% Standard beamer'}
```

Content to convert:
{paper_excerpt}

Rules:
- [TEXT] → frame text, keep ALL sentences
- [ITEM]/[ENUM] → \\begin{{itemize}} or \\begin{{enumerate}}
- [FORMULA] → \\begin{{equation*}}...\\end{{equation*}} or inline $...$, copy EXACTLY
- [TABLE] → booktabs table with \\toprule, \\midrule, \\bottomrule; use \\resizebox{{\\textwidth}}{{!}}{{...}} if wide
- [FIGURE] → \\includegraphics[width=\\textwidth,height=0.6\\textheight,keepaspectratio]{{images/filename}}
- [USE \\section{{X}}] / [USE \\subsection{{X}}] / [USE \\subsubsection{{X}}] →
  emit EXACTLY that LaTeX command with EXACTLY that title. NEVER change the section level.
- Frame format: \\begin{{frame}}{{Descriptive Title}} ... \\end{{frame}}
- CRITICAL: EVERY \\begin{{frame}} MUST have \\end{{frame}}
- Frame titles: PLAIN TEXT only (no \\cmd{{}} commands in braces). Use $x$ for math in titles.
- ONE topic per frame; split if too full (use "Title (continued)" for overflow)
- Preserve ALL \\cite{{...}} references
- Start with \\titlepage frame + \\tableofcontents frame
- End with \\end{{document}}
- NO preamble, NO \\documentclass, NO \\usepackage, NO \\begin{{document}}
- CONVERT everything, OMIT nothing."""

    def _build_abstract_prompt(
        self,
        template_body: str,
        paper_content: str,
    ) -> str:
        """Build a prompt for abstract mode — LLM first analyzes the paper,
        then generates a well-structured Beamer presentation."""
        body_excerpt = template_body[:3000] if len(template_body) > 3000 else template_body

        return f"""You are an expert academic presenter. Your task is to create a clear, engaging Beamer presentation that summarizes a research paper.

The preamble is already provided — do NOT generate preamble, \\documentclass, or \\usepackage.

## LANGUAGE RULE (CRITICAL)
Keep ALL text in English — the ORIGINAL language of the paper. The template may include CJK fonts or packages; these are for styling only. NEVER translate content to Chinese, Japanese, or any other language. Every paragraph, section title, and frame title must be in English.

## TEMPLATE FRAME STYLE (follow these patterns for colors, fonts, frame structure)
```latex
{body_excerpt if body_excerpt else '% Standard beamer style'}
```

## PAPER INFORMATION
{paper_content}

## YOUR TASK: Two-Step Process

### Step 1 — Analyze the Paper
Read the abstract carefully and identify the core narrative:
- **Background & Problem:** What problem does this paper address? Why is it important?
- **Methodology:** What approach / method / framework does the paper propose? What's the key innovation?
- **Key Results:** What are the main findings? Any surprising or important numbers?
- **Significance:** What is the takeaway? Why should the audience care?

### Step 2 — Create Beamer Frames
Based on your analysis, generate frames that tell a clear story. Structure:

1. **Title frame:** \\begin{{frame}}\\titlepage\\end{{frame}}
2. **Background / Motivation:** Why this problem matters (1 frame)
3. **Method / Approach:** The key idea, explained clearly (1-2 frames)
4. **Key Results / Findings:** The main outcomes (1-2 frames)
5. **Summary / Takeaway:** What the audience should remember (1 frame)

## GUIDELINES

- **Be interpretive, not just a copy machine:** Rewrite the abstract content into presentation language — short sentences, clear logic flow, highlight key points
- **Use bullet points** (\\begin{{itemize}}) for listing key ideas — they're easier to read on slides than paragraphs
- **Frame titles should tell a story:** Not just "Abstract" but e.g. "Motivation: Why Multi-Source DA?", "Method: Distributionally Robust Optimization", "Results: Improved Generalization"
- **Match the template's visual style** (colors, block environments, fonts)
- **Keep each frame focused** — one main idea per frame
- **Output ONLY** body LaTeX (from first frame to \\end{{document}}), wrapped in ```latex ... ```
- End with \\end{{document}}

Generate now — remember: analyze first, then present:"""
    # Template reading
    # ------------------------------------------------------------------

    def _read_template(self, template_dir: Path) -> tuple[str, str, str]:
        """Read template, splitting into preamble / body / post-document."""
        tex_files = list(template_dir.glob("*.tex"))
        if not tex_files:
            return self._read_template_from_sty(template_dir)

        tex_content = Path(tex_files[0]).read_text(encoding="utf-8",
                                                    errors="replace")

        begin_match = re.search(r'\\begin\{document\}', tex_content)
        end_match = re.search(r'\\end\{document\}', tex_content)

        if not begin_match:
            return tex_content, "", ""

        preamble = tex_content[:begin_match.start()].strip()
        if end_match:
            body = tex_content[begin_match.end():end_match.start()].strip()
            post = tex_content[end_match.start():].strip()
        else:
            body = tex_content[begin_match.end():].strip()
            post = r"\end{document}"

        return preamble, body, post

    def _read_template_from_sty(self, template_dir: Path) -> tuple[str, str, str]:
        """Build basic template info from .sty files only."""
        sty_files = list(template_dir.glob("*.sty"))
        sty_names = [f.stem for f in sty_files]

        # Generate proper preamble from available .sty files
        lines = [r"\documentclass[11pt,aspectratio=169]{beamer}"]
        for name in sty_names:
            lines.append(rf"\usepackage{{{name}}}")
        preamble = "\n".join(lines)
        return preamble, "", r"\end{document}"

    # ------------------------------------------------------------------
    # Response extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_body(response: str) -> str:
        """Extract body LaTeX from LLM response (may be in code block)."""
        # Try ```latex ... ``` first
        m = re.search(r'```(?:latex)?\s*\n?(.*?)```', response, re.DOTALL)
        if m:
            tex = m.group(1).strip()
        else:
            tex = response.strip()

        # Strip preamble if present (LLM may ignore instructions)
        doc_match = re.search(r'\\begin\{document\}', tex)
        if doc_match:
            tex = tex[doc_match.end():]

        # Strip \end{document} if present (we add it later)
        end_match = re.search(r'\\end\{document\}', tex)
        if end_match:
            tex = tex[:end_match.start()]

        return tex.strip()

    # ------------------------------------------------------------------
    # LLM error fixes
    # ------------------------------------------------------------------

    @staticmethod
    def _fix_llm_errors(body: str) -> str:
        """Fix common LLM-generated LaTeX errors. These are IRON RULES
        that guarantee structural correctness regardless of LLM output."""

        # === TRIVIAL FIXES (no structural impact) ===
        body = body.replace(r'\insertemail', r'\texttt{email}')

        # LLM fix responses sometimes bleed "FRAME N: Title" label lines
        # into the body when the LLM doesn't wrap its output in ```latex.
        # These lines look like LaTeX to xelatex (it tries to parse FRAME
        # as a command), causing "File ended while scanning use of \frame".
        body = re.sub(r'^FRAME\s+\d+:.*$', '', body, flags=re.MULTILINE)

        # \begin{array} inside inline $...$ causes "Argument of \frame has
        # an extra }" because LaTeX parses \begin{array} brace arguments
        # as part of the frame parameter scan.  Move it to display math.
        body = re.sub(
            r'\$(\\begin\{array\}.*?\\end\{array\})\$',
            r'\\[\1\\]',
            body, flags=re.DOTALL,
        )
        body = re.sub(
            r'\{figs/([a-f0-9]{64}\.[a-z]+)\}',
            r'{images/\1}', body,
        )
        # Remove environments whose packages are not loaded in typical
        # Beamer templates — removing them avoids "Environment X undefined"
        # compile errors without losing meaningful paper content (these
        # are all LLM-invented decorations, not paper content).
        _pkg_less_envs = [
            'algorithmic', 'algorithm', 'algorithm2e',
            'tikzpicture', 'tikzcd',
            'lstlisting',
        ]
        for _env in _pkg_less_envs:
            body = re.sub(
                rf'\\begin\{{{_env}\}}.*?\\end\{{{_env}\}}',
                '', body, flags=re.DOTALL,
            )
        for cmd in ['\\For', '\\State', '\\EndFor', '\\If', '\\Else',
                     '\\EndIf', '\\While', '\\EndWhile', '\\Return']:
            body = body.replace(cmd, '')

        # Remove custom enumerate labels [(a)], [(b)], [(i)] etc.
        # These require the enumerate package which may conflict with
        # beamer's built-in enumerate handling.  The LLM often emits
        # \begin{enumerate}[(a)] which breaks compilation.
        body = re.sub(
            r'(\\begin\{enumerate\})\[\([a-zA-Z0-9]+\)\]',
            r'\1', body,
        )
        body = re.sub(
            r'(\\begin\{enumerate\})\[.*?label=.*?\]',
            r'\1', body,
        )
        # Similarly for itemize with custom bullet options
        body = re.sub(
            r'(\\begin\{itemize\})\[.*?\]',
            r'\1', body,
        )

        # === STRUCTURAL FIXES (guarantee correctness) ===
        body = LLMBeamerConverter._fix_title_braces(body)

        # Fix \tag usage: \tag only works in \begin{equation} (not $$ or equation*)
        body = LLMBeamerConverter._fix_tag_environments(body)

        # Fix section hierarchy by numbering
        body = LLMBeamerConverter._fix_section_hierarchy(body)

        # UNIVERSAL: ensure ALL \begin{env} / \end{env} are properly paired
        body = LLMBeamerConverter._fix_all_environments(body)

        return body

    @staticmethod
    def _fix_tag_environments(body: str) -> str:
        """Remove \\tag where LaTeX won't accept it.

        \\tag is legal inside equation, equation*, align, align*, gather,
        gather*, multline(*), alignat(*), flalign(*), eqnarray(*) and
        nowhere else — in particular NOT inside $...$, \\(...\\), \\[...\\],
        $$...$$, or in regular text. The LLM frequently emits \\tag inside
        $$...$$ or \\[...\\]; deleting the \\tag preserves the formula and
        keeps the original numbering state (numbered vs unnumbered) of
        whatever the LLM chose.

        We intentionally do NOT rewrite equation*→equation or align*→align.
        The starred variants are what the paper uses to suppress numbering,
        and the unstarred variants both accept \\tag, so the LLM's choice
        is correct as-is."""
        import re as _re

        TAG_OK_ENVS = {
            'equation', 'equation*',
            'align', 'align*',
            'gather', 'gather*',
            'multline', 'multline*',
            'alignat', 'alignat*',
            'flalign', 'flalign*',
            'eqnarray', 'eqnarray*',
        }

        # Walk through the body, tracking which math environment (if any)
        # we are inside. Strip \tag{...} / \tag*{...} whenever we are NOT
        # inside one that allows it.
        env_stack: list[str] = []
        in_dollar_dollar = False
        in_dollar = False
        in_bracket_display = False  # \[ ... \]
        in_paren_inline = False     # \( ... \)

        out = []
        i = 0
        n = len(body)
        while i < n:
            # \begin{env}
            m = _re.match(r'\\begin\{([^}]+)\}', body[i:])
            if m:
                env_stack.append(m.group(1).strip())
                out.append(m.group(0))
                i += m.end()
                continue
            # \end{env}
            m = _re.match(r'\\end\{([^}]+)\}', body[i:])
            if m:
                env = m.group(1).strip()
                if env_stack and env_stack[-1] == env:
                    env_stack.pop()
                out.append(m.group(0))
                i += m.end()
                continue
            # \[ ... \]
            if body.startswith('\\[', i):
                in_bracket_display = True
                out.append('\\[')
                i += 2
                continue
            if body.startswith('\\]', i):
                in_bracket_display = False
                out.append('\\]')
                i += 2
                continue
            # \( ... \)
            if body.startswith('\\(', i):
                in_paren_inline = True
                out.append('\\(')
                i += 2
                continue
            if body.startswith('\\)', i):
                in_paren_inline = False
                out.append('\\)')
                i += 2
                continue
            # $$
            if body.startswith('$$', i):
                in_dollar_dollar = not in_dollar_dollar
                out.append('$$')
                i += 2
                continue
            # $ (single)
            if body[i] == '$' and (i == 0 or body[i - 1] != '\\'):
                in_dollar = not in_dollar
                out.append('$')
                i += 1
                continue
            # \tag{...} or \tag*{...}
            m = _re.match(r'\\tag\*?\s*\{', body[i:])
            if m:
                # Find matching }
                depth = 1
                j = i + m.end()
                while j < n and depth > 0:
                    if body[j] == '\\' and j + 1 < n and body[j + 1] in '{}':
                        j += 2
                        continue
                    if body[j] == '{':
                        depth += 1
                    elif body[j] == '}':
                        depth -= 1
                    j += 1
                tag_end = j  # position after final }
                # Are we currently in a tag-OK environment?
                in_math_env = (
                    env_stack and env_stack[-1] in TAG_OK_ENVS
                )
                if (in_math_env
                        and not in_dollar_dollar
                        and not in_dollar
                        and not in_bracket_display
                        and not in_paren_inline):
                    # legal context — keep the \tag
                    out.append(body[i:tag_end])
                # else: drop the \tag entirely. Numbering choice of the
                # surrounding environment is preserved.
                i = tag_end
                continue
            out.append(body[i])
            i += 1

        return ''.join(out)

    @staticmethod
    def _fix_section_hierarchy(body: str) -> str:
        """Fix section/subsection level by section number:
        '1. X' → \\section{X}, '1.2. X' → \\subsection{X},
        '1.2.1. X' → \\subsubsection{X}."""
        import re as _re

        def _correct_level(m):
            num = m.group(1)   # 1.2.3.
            title = m.group(2)  # Title text
            dots = num.count('.')
            if dots == 1:
                return f'\\section{{{title}}}'
            elif dots == 2:
                return f'\\subsection{{{title}}}'
            else:
                return f'\\subsubsection{{{title}}}'

        # Match \section{1.2. Title} or \subsection{1.2.3. Title} etc.
        for cmd in ['section', 'subsection', 'subsubsection']:
            body = _re.sub(
                rf'\\{cmd}\{{(\d+(?:\.\d+)*\.?)\s+(.+?)\}}',
                _correct_level,
                body,
            )
        return body

    @staticmethod
    def _scan_envs(body: str) -> list[tuple[int, str, str]]:
        """Tokenize body into ordered (pos, kind, env_name) events for every
        \\begin{X}/\\end{X}. Skips % comment lines and \\verb regions.
        Returns events sorted by source position."""
        events: list[tuple[int, str, str]] = []
        for m in re.finditer(r'\\(begin|end)\s*\{([^}]+)\}', body):
            pos = m.start()
            # Skip if inside a % comment on this line
            line_start = body.rfind('\n', 0, pos) + 1
            line_prefix = body[line_start:pos]
            # An odd number of unescaped % before pos = inside comment
            stripped = re.sub(r'\\%', '', line_prefix)
            if '%' in stripped:
                continue
            events.append((pos, m.group(1), m.group(2).strip()))
        return events

    @staticmethod
    def _validate_env_pairs(body: str) -> list[dict]:
        """Stack-based check: every \\begin{X} must be closed by \\end{X}
        in nesting order. Returns list of problems with details. This is
        the source of truth — no whitelist, every environment is checked."""
        events = LLMBeamerConverter._scan_envs(body)
        stack: list[tuple[int, str]] = []  # (pos, env)
        problems: list[dict] = []
        for pos, kind, env in events:
            if kind == 'begin':
                stack.append((pos, env))
            else:  # end
                if not stack:
                    line = body.count('\n', 0, pos) + 1
                    problems.append({
                        'kind': 'orphan_end',
                        'env': env,
                        'pos': pos,
                        'line': line,
                    })
                    continue
                top_pos, top_env = stack[-1]
                if top_env == env:
                    stack.pop()
                else:
                    # Mismatch — pop until we find a match, or report
                    found_idx = None
                    for k in range(len(stack) - 1, -1, -1):
                        if stack[k][1] == env:
                            found_idx = k
                            break
                    if found_idx is not None:
                        for unclosed in stack[found_idx + 1:]:
                            up_line = body.count('\n', 0, unclosed[0]) + 1
                            problems.append({
                                'kind': 'unclosed_inner',
                                'env': unclosed[1],
                                'pos': unclosed[0],
                                'line': up_line,
                            })
                        stack = stack[:found_idx]
                    else:
                        line = body.count('\n', 0, pos) + 1
                        problems.append({
                            'kind': 'orphan_end',
                            'env': env,
                            'pos': pos,
                            'line': line,
                        })
        for unclosed_pos, unclosed_env in stack:
            line = body.count('\n', 0, unclosed_pos) + 1
            problems.append({
                'kind': 'unclosed',
                'env': unclosed_env,
                'pos': unclosed_pos,
                'line': line,
            })
        return problems

    @staticmethod
    def _fix_all_environments(body: str) -> str:
        """Universal stack-based \\begin{}/\\end{} repair. Works for ANY
        environment (frame, enumerate, itemize, equation, theorem, proof,
        block, columns, tikzpicture, tabular, ...). Not a whitelist —
        every \\begin{} must have its matching \\end{} in nesting order.

        Repair strategy: walk events left-to-right with a stack.
        - On \\begin{X}: push.
        - On \\end{X}:
          - If stack top is X: pop (matched).
          - If X appears deeper in stack: auto-close inner unmatched
            environments by inserting their \\end before this position.
          - If X is nowhere in stack: drop the orphan \\end{X}.
        - At EOF: close all remaining open environments in reverse order.

        This guarantees the output is structurally balanced regardless of
        what the LLM produced. Any remaining semantic issues (wrong content
        between tags) are caught by the compile-and-fix loop downstream."""
        events = LLMBeamerConverter._scan_envs(body)
        if not events:
            return body

        # Plan repairs as (insert_pos, text_to_insert) and
        # (delete_start, delete_end) deletions, then apply in reverse.
        insertions: list[tuple[int, str]] = []
        deletions: list[tuple[int, int]] = []
        stack: list[tuple[int, str]] = []  # (begin_pos, env)

        for pos, kind, env in events:
            if kind == 'begin':
                stack.append((pos, env))
                continue
            # kind == 'end'
            end_token_end = pos + len(f'\\end{{{env}}}')
            if stack and stack[-1][1] == env:
                stack.pop()
                continue
            # Look deeper for matching begin
            found_idx = None
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][1] == env:
                    found_idx = k
                    break
            if found_idx is not None:
                # Close all inner-unmatched envs before this \end
                inner = stack[found_idx + 1:]
                if inner:
                    insertion_text = '\n' + '\n'.join(
                        f'\\end{{{e}}}' for _pos, e in reversed(inner)
                    ) + '\n'
                    insertions.append((pos, insertion_text))
                stack = stack[:found_idx]
            else:
                # Orphan \end — delete the whole token
                deletions.append((pos, end_token_end))

        # Close remaining open envs at EOF
        if stack:
            tail = '\n' + '\n'.join(
                f'\\end{{{e}}}' for _pos, e in reversed(stack)
            ) + '\n'
            insertions.append((len(body), tail))

        # Apply edits from the back so positions stay valid.
        edits: list[tuple[int, int, str]] = []
        for p, t in insertions:
            edits.append((p, p, t))
        for s, e in deletions:
            edits.append((s, e, ''))
        edits.sort(key=lambda x: x[0], reverse=True)

        out = body
        for s, e, t in edits:
            out = out[:s] + t + out[e:]
        return out



    @staticmethod
    def _fix_title_braces(body: str) -> str:
        """Fix brace commands inside frame/section titles that cause
        'File ended while scanning use of \\@writefile' errors.

        \\cmd{X} → \\cmd X in \\begin{frame}{...}, \\section{...}, etc.
        """
        font_cmds = [
            r'\mathcal', r'\mathbf', r'\mathbb', r'\mathit',
            r'\mathrm', r'\mathsf', r'\mathtt',
        ]
        accent_cmds = [
            r'\widehat', r'\widetilde', r'\bar', r'\tilde',
            r'\hat', r'\dot', r'\ddot',
        ]
        # Patterns: command that opens a brace group whose content
        # will be written to .aux/.toc as a moving argument
        title_openers = [
            r'\begin{frame}{',
            r'\section{',
            r'\subsection{',
            r'\subsubsection{',
        ]

        def _fix_title(title: str) -> str:
            for cmd in font_cmds:
                title = re.sub(
                    re.escape(cmd) + r'\{([^}]+?)\}',
                    lambda m: cmd + ' ' + m.group(1),
                    title,
                )
            for cmd in accent_cmds:
                title = re.sub(
                    re.escape(cmd) + r'\{([^}]+?)\}',
                    lambda m: cmd + ' ' + m.group(1),
                    title,
                )
            # Replace escaped special chars in titles with plain text
            # (these cause \\HyPL@Entry / \\@writefile errors in moving args)
            title = title.replace(r'\&', 'and')
            title = title.replace(r'\%', '%')
            title = title.replace(r'\#', '#')
            return title

        result = []
        i = 0
        while i < len(body):
            # Find the earliest title opener from current position
            earliest_pos = len(body)
            earliest_opener = ''
            for opener in title_openers:
                pos = body.find(opener, i)
                if pos != -1 and pos < earliest_pos:
                    earliest_pos = pos
                    earliest_opener = opener

            if earliest_pos == len(body):
                result.append(body[i:])
                break

            # Copy up to and including the opener
            prefix_end = earliest_pos + len(earliest_opener)
            result.append(body[i:prefix_end])
            i = prefix_end

            # Parse title — count brace depth, skipping escaped braces
            depth = 1
            j = i
            while j < len(body) and depth > 0:
                if body[j] == '\\' and j + 1 < len(body):
                    if body[j + 1] in '{}':
                        j += 2
                        continue
                if body[j] == '{':
                    depth += 1
                elif body[j] == '}':
                    depth -= 1
                j += 1

            title = body[i:j - 1]  # exclude closing }
            result.append(_fix_title(title))
            result.append('}')  # closing brace
            i = j  # continue after title

        return ''.join(result)

    # ------------------------------------------------------------------
    # LLM API call
    # ------------------------------------------------------------------

    async def _call_llm(self, prompt: str, max_tokens: int = 32768) -> str:
        import aiohttp
        import asyncio
        import socket

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": "You are an expert LaTeX Beamer presenter. Generate compilable, well-structured beamer frames following specific templates. Output only valid LaTeX code. CRITICAL: Keep ALL text in the ORIGINAL language of the paper (English). The template's font/package settings are for styling ONLY — never translate content."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        last_error = None
        for attempt in range(3):
            try:
                connector = aiohttp.TCPConnector(
                    family=socket.AF_INET,
                    force_close=True,
                    enable_cleanup_closed=True,
                )
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=600),
                    ) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(
                                f"LLM API error {resp.status}: {text[:500]}")
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
            except (
                asyncio.TimeoutError,
                RuntimeError,
                aiohttp.ClientError,
                OSError,
            ) as e:
                last_error = e
                if attempt < 2:
                    import sys
                    print(f"  LLM call failed (attempt {attempt+1}/3), retrying...",
                          file=sys.stderr)
                    await asyncio.sleep((attempt + 1) * 15)

        raise last_error  # type: ignore[misc]

    @staticmethod
    def _filter_sections(sections):
        """Filter out appendix, supplementary, proofs, and malformed sections."""
        skip_keywords = [
            "appendix", "supplementary", "supplement to",
            "proofs", "proof of",
        ]
        result = []
        for sec in sections:
            title_lower = sec.title.lower().strip()
            # Keyword match
            if any(kw in title_lower for kw in skip_keywords):
                continue
            # Bullet-point heading (malformed — likely appendix formula content)
            if title_lower.startswith("•") or title_lower.startswith("-"):
                continue
            # Pure math heading (starts with $ or \( — appendix formula)
            if title_lower.startswith("$") or title_lower.startswith("\\("):
                continue
            result.append(sec)
        return result if result else sections

    # ------------------------------------------------------------------
    # Document formatting for prompts
    # ------------------------------------------------------------------

    def _format_document(self, doc: Document, mode: OutputMode) -> str:
        """Format paper content as structured text for the LLM prompt."""
        lines = [
            f"TITLE: {doc.title}",
            f"AUTHORS: {', '.join(doc.authors)}",
            f"ABSTRACT: {doc.abstract[:2000] if doc.abstract else 'N/A'}",
        ]

        if mode == OutputMode.ABSTRACT:
            lines.append("\nMODE: abstract only — just title + abstract slides")
            return "\n".join(lines)

        lines.append(f"\nMODE: full paper — all sections needed")

        # Filter out appendix/supplementary/proofs sections
        main_sections = self._filter_sections(doc.sections)

        lines.append(f"SECTIONS ({len(main_sections)}):")

        _LEVEL_CMD = {1: r'\section', 2: r'\subsection', 3: r'\subsubsection'}

        def _heading_only(title: str) -> str:
            return re.sub(r'^[\d]+(?:\.[\d]+)*\.?\s+', '', title).strip()

        def _emit_section(sec, indent: str = ''):
            cmd = _LEVEL_CMD.get(sec.level, r'\subsubsection')
            clean = _heading_only(sec.title)
            lines.append(f"\n{indent}[USE {cmd}{{{clean}}}]")
            for block in sec.blocks:
                blk = self._format_block(block)
                if blk:
                    lines.append(f"{indent}{blk}")
            for sub in sec.subsections[:20]:
                _emit_section(sub, indent + '  ')

        for sec in main_sections:
            _emit_section(sec)

        return "\n".join(lines)

    def _format_block(self, block) -> str | None:
        bt = block.type
        content = block.content
        if bt == BlockType.HEADING:
            return f"[HEADING L{block.heading_level}] {content}"
        elif bt == BlockType.PARAGRAPH:
            return f"[TEXT] {content}"
        elif bt == BlockType.FORMULA_DISPLAY:
            return f"[FORMULA] {content}"
        elif bt == BlockType.FIGURE:
            img = block.image_path or ""
            cap = block.caption or ""
            return f"[FIGURE] caption={cap}, image={Path(img).name if img else 'N/A'}"
        elif bt == BlockType.TABLE:
            cap = block.caption or ""
            rows = len(block.lines) if block.lines else 0
            return f"[TABLE rows={rows}] caption={cap}\n{content}"
        elif bt == BlockType.LIST_ITEM:
            return f"[ITEM] {content}"
        elif bt == BlockType.ENUM_ITEM:
            return f"[ENUM] {content}"
        elif bt == BlockType.CITATION:
            return f"[CITE] {content}"
        else:
            return f"[{bt.value}] {content}"


def _escape_tex(text: str) -> str:
    """Escape special LaTeX characters for use in \\title, \\author, etc."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\^{}",
        "\\": r"\textbackslash{}",
    }
    for char, repl in replacements.items():
        text = text.replace(char, repl)
    return text
