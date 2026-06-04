"""Background job processing pipeline — ties all core components together."""

import datetime
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from paper2beamer.config import settings
from paper2beamer.core.models import OutputMode, ExtractResult
from paper2beamer.core.hashing import hash_pdf
from paper2beamer.core.extractor import create_extractor
from paper2beamer.core.parser import MarkdownParser
from paper2beamer.core.converter import BeamerConverter
from paper2beamer.core.splitter import FrameSplitter
from paper2beamer.core.compiler import LatexCompiler
from paper2beamer.cache.manager import CacheManager
from paper2beamer.db.models import Job, JobStatus
from paper2beamer.utils.file_utils import create_zip, collect_directory_files, collect_directory_recursive


async def process_job(
    job_id: str,
    pdf_path: str,
    mode: str,
    session_factory,
    template_id: str | None = None,
    bypass_cache: bool = False,
):
    """Main processing pipeline for a conversion job."""
    from paper2beamer.db.database import get_session_factory
    session_factory = get_session_factory()

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return

        try:
            pdf_hash = hash_pdf(pdf_path)
            cache_mgr = CacheManager(settings.cache_dir)
            extractor = create_extractor(
                mode=settings.mineru_mode,
                api_url=settings.mineru_api_url,
                api_key=settings.mineru_api_key,
                timeout=settings.mineru_timeout,
            )
            parser = MarkdownParser()
            converter = BeamerConverter()
            splitter = FrameSplitter()
            compiler = LatexCompiler(
                engine=settings.tex_engine,
                timeout=settings.latex_timeout,
            )
            output_mode = OutputMode(mode)
            output_dir = Path(settings.output_dir) / job_id
            output_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Extract (or load from cache)
            extract_result = None
            if not bypass_cache:
                await _update_job(session, job, JobStatus.EXTRACTING, 10)
                cached = await cache_mgr.get(session, pdf_hash)
                if cached:
                    extract_result = cached

            if extract_result is None:
                await _update_job(session, job, JobStatus.EXTRACTING, 20)
                extract_result = await extractor.extract(
                    pdf_path, output_dir / "extract"
                )
                await cache_mgr.put(
                    session, pdf_hash, extract_result, Path(pdf_path).name
                )

            # Step 2: Parse Markdown → Document
            await _update_job(session, job, JobStatus.CONVERTING, 40)
            document = parser.parse(
                extract_result.markdown, extract_result.images_dir
            )

            # Step 3: Resolve template directory
            await _update_job(session, job, JobStatus.CONVERTING, 40)
            template_dir = ""
            if template_id:
                template_dir = str(
                    Path(settings.template_dir) / template_id
                )
            if not template_dir or not Path(template_dir).exists():
                template_dir = str(
                    Path(__file__).parent.parent.parent / "templates" / "default"
                )

            # Step 5: Convert Document → Beamer LaTeX
            # Use LLM converter when API key is available (template-aware generation)
            await _update_job(session, job, JobStatus.CONVERTING, 60)
            from paper2beamer.core.llm_converter import LLMBeamerConverter
            llm_converter = LLMBeamerConverter()
            if llm_converter.enabled:
                beamer_tex = await llm_converter.convert(
                    document, Path(template_dir), output_mode
                )
            else:
                beamer_tex = converter.convert(document, template_dir, output_mode)

            # Step 6: Split frames (skip for LLM output — already well-structured)
            if not llm_converter.enabled:
                beamer_tex = splitter.split(beamer_tex)

            # Step 6: Compile LaTeX → PDF
            # When the LLM converter is enabled we run compile-and-fix:
            # LaTeX errors are sent back to the LLM (no human intervention)
            # and the regenerated frames are retried until it compiles or
            # the attempt budget is exhausted.
            await _update_job(session, job, JobStatus.COMPILING, 80)

            async def _compile_once(tex: str) -> tuple[bytes, str]:
                return await compiler.compile(
                    tex_content=tex,
                    output_dir=str(output_dir),
                    template_dirs=[template_dir],
                    images_dir=extract_result.images_dir,
                )

            if llm_converter.enabled:
                # Read the template body again so the LLM repair prompt has
                # styling context. Cheap — already on disk.
                _, template_body, _ = llm_converter._read_template(
                    Path(template_dir)
                )
                beamer_tex, pdf_bytes, log_text = \
                    await llm_converter.compile_and_fix(
                        beamer_tex,
                        _compile_once,
                        template_body,
                        max_attempts=settings.llm_fix_attempts,
                    )
            else:
                pdf_bytes, log_text = await _compile_once(beamer_tex)

            pdf_skipped = False
            if not pdf_bytes:
                # Always persist .tex + log so the user (or a downstream
                # developer) can inspect what was generated and why
                # compilation failed — even when we ultimately raise.
                try:
                    (output_dir / "main.tex").write_text(
                        beamer_tex, encoding="utf-8"
                    )
                    (output_dir / "build.log").write_text(
                        log_text, encoding="utf-8", errors="replace"
                    )
                except OSError:
                    pass
                # If latexmk is not installed, still package .tex without .pdf
                if "not found" in log_text or "找不到" in log_text:
                    pdf_skipped = True
                else:
                    raise RuntimeError(
                        f"LaTeX compilation failed after "
                        f"{settings.llm_fix_attempts if llm_converter.enabled else 1} "
                        f"attempt(s). See {output_dir}/main.tex and "
                        f"{output_dir}/build.log.\n\n{log_text[-2000:]}"
                    )

            # Step 7: Package output ZIP
            await _update_job(session, job, JobStatus.COMPILING, 90)
            tex_path = output_dir / "main.tex"
            pdf_path_out = output_dir / "presentation.pdf"
            zip_path = output_dir / "presentation.zip"

            tex_path.write_text(beamer_tex, encoding="utf-8")
            if pdf_bytes:
                pdf_path_out.write_bytes(pdf_bytes)

            zip_files: dict[str, str | bytes] = {
                "main.tex": beamer_tex,
                "build.log": log_text,
                "README.txt": _build_readme(document, output_mode, pdf_skipped),
            }
            if pdf_bytes:
                zip_files["presentation.pdf"] = pdf_bytes

            img_files = collect_directory_files(
                extract_result.images_dir, prefix="images/"
            )
            zip_files.update(img_files)
            tpl_files = collect_directory_recursive(
                template_dir, prefix="", exclude_names={"main.tex"}
            )
            zip_files.update(tpl_files)

            create_zip(zip_path, zip_files)

            # Complete
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100
            job.output_zip_path = str(zip_path)
            job.output_tex_path = str(tex_path)
            job.output_pdf_path = str(pdf_path_out) if pdf_bytes else None
            job.log_text = log_text
            job.completed_at = datetime.datetime.utcnow()
            await session.commit()

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.datetime.utcnow()
            await session.commit()


async def _update_job(session: AsyncSession, job: Job, status: JobStatus,
                      progress: int):
    job.status = status
    job.progress_percent = progress
    await session.commit()


def _build_readme(document, output_mode: OutputMode, pdf_skipped: bool = False) -> str:
    lines = [
        f"Beamer presentation generated by paper2beamer",
        f"==============================================\n",
        f"Paper: {document.title}",
        f"Mode: {output_mode.value}",
        f"Sections: {len(document.sections)}\n",
        f"Files:",
        f"  - main.tex          : Beamer LaTeX source",
    ]
    if pdf_skipped:
        lines.append(
            f"  - presentation.pdf  : NOT GENERATED (latexmk not found)\n"
            f"\nTo compile the PDF, install texlive + latexmk and run:\n"
            f"  latexmk -pdf -pdflatex main.tex"
        )
    else:
        lines.append(f"  - presentation.pdf  : Compiled presentation")
    lines.extend([
        f"  - build.log         : LaTeX compilation log",
        f"  - images/           : Extracted figures",
    ])
    return "\n".join(lines)
