"""LaTeX compiler — wraps latexmk for Beamer PDF generation."""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path


class LatexCompiler:
    def __init__(self, engine: str = "pdflatex", timeout: int = 120):
        self.engine = engine
        self.timeout = timeout

    async def compile(
        self,
        tex_content: str,
        output_dir: str | Path,
        template_dirs: list[str] | None = None,
        images_dir: str | Path = "",
        bib_content: str = "",
    ) -> tuple[bytes, str]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        work_dir = Path(tempfile.mkdtemp(prefix="paper2beamer_"))

        try:
            tex_file = work_dir / "presentation.tex"
            tex_file.write_text(tex_content, encoding="utf-8")

            # Copy paper images. The LLM converter and programmatic
            # converter both write \includegraphics{images/<hash>.jpg},
            # so the images must land in <work>/images/, not the root.
            # Also copy to root as a fallback for older / non-LLM paths
            # that may emit bare {<hash>.jpg}.
            images_src = Path(images_dir) if images_dir else None
            if images_src and images_src.exists():
                images_dest = work_dir / "images"
                images_dest.mkdir(parents=True, exist_ok=True)
                for img in images_src.iterdir():
                    if img.is_file():
                        shutil.copy2(img, images_dest / img.name)
                        shutil.copy2(img, work_dir / img.name)

            # Copy template support files (fonts, logos, figures, bib files)
            # so that relative paths like fonts/xxx.ttf or figs/logo.pdf work
            for td in (template_dirs or []):
                td_path = Path(td)
                if td_path.exists():
                    for item in td_path.rglob("*"):
                        if item.is_file():
                            # Preserve subdirectory structure relative to template dir
                            rel = item.relative_to(td_path)
                            dest = work_dir / rel
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(item, dest)

            if bib_content:
                bib_file = work_dir / "references.bib"
                bib_file.write_text(bib_content, encoding="utf-8")

            env = self._build_env(template_dirs or [], work_dir)

            cmd = [
                "latexmk",
                "-pdf",
                f"-{self.engine}",
                "-interaction=nonstopmode",
                "-halt-on-error",
                str(tex_file.name),
            ]

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(work_dir),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                return b"", (
                    f"LaTeX compiler '{cmd[0]}' not found. "
                    "Install texlive (or equivalent) with latexmk to enable PDF compilation. "
                    "On Ubuntu/Debian: sudo apt install texlive-latex-extra latexmk\n"
                    "On macOS: brew install mactex\n"
                    "On Windows: install MiKTeX or TeX Live from https://tug.org/texlive/"
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                # Still try to read the partial .log — the timeout may be
                # a symptom of a real error (e.g. font loop, bad package).
                partial_log = work_dir / "presentation.log"
                tail = ""
                if partial_log.exists():
                    try:
                        tail = partial_log.read_text(
                            encoding="utf-8", errors="replace"
                        )[-8000:]
                    except OSError:
                        pass
                return b"", (
                    f"LaTeX compilation timed out after {self.timeout}s.\n\n"
                    + tail
                )

            log_text = stdout.decode("utf-8", errors="replace")
            if stderr:
                log_text += "\n" + stderr.decode("utf-8", errors="replace")

            pdf_file = work_dir / "presentation.pdf"
            if pdf_file.exists():
                pdf_bytes = pdf_file.read_bytes()
            else:
                pdf_bytes = b""
                # Read the .log file directly — latexmk's stdout is a
                # summary; the full log (with `l.NNN <source>` lines we
                # need for diagnostics) is on disk.
                full_log = work_dir / "presentation.log"
                if full_log.exists():
                    try:
                        log_text = full_log.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError:
                        pass

            return pdf_bytes, log_text

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _build_env(self, template_dirs: list[str], work_dir: Path) -> dict:
        env = os.environ.copy()
        texinputs_parts = [str(work_dir)]
        texinputs_parts.extend(template_dirs)
        texinputs = os.pathsep.join(texinputs_parts)
        existing = env.get("TEXINPUTS", "")
        if existing:
            texinputs += os.pathsep + existing
        env["TEXINPUTS"] = texinputs + os.pathsep
        env["max_print_line"] = "10000"
        env["error_line"] = "254"
        env["half_error_line"] = "238"
        return env

    def _extract_errors(self, log_text: str) -> str:
        error_lines: list[str] = []
        for line in log_text.splitlines():
            if line.startswith("! ") or "Error" in line or "error" in line:
                error_lines.append(line)
        if error_lines:
            return "\n".join(error_lines[-20:])
        return log_text[-2000:]
