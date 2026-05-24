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
from paper2beamer.core.citations import CitationDetector
from paper2beamer.cache.manager import CacheManager
from paper2beamer.db.models import Job, JobStatus
from paper2beamer.utils.file_utils import create_zip, collect_directory_files


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
            citation_detector = CitationDetector()

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

            # Step 3: Citations
            citations, bib_text = citation_detector.extract(document)

            # Step 4: Convert Document → Beamer LaTeX
            await _update_job(session, job, JobStatus.CONVERTING, 60)
            template_dir = ""
            if template_id:
                template_dir = str(
                    Path(settings.template_dir) / template_id
                )
            if not template_dir or not Path(template_dir).exists():
                template_dir = str(
                    Path(__file__).parent.parent.parent / "templates" / "default"
                )

            beamer_tex = converter.convert(document, template_dir, output_mode)

            # Step 5: Split frames
            beamer_tex = splitter.split(beamer_tex)

            # Step 6: Compile LaTeX → PDF
            await _update_job(session, job, JobStatus.COMPILING, 80)
            pdf_bytes, log_text = await compiler.compile(
                tex_content=beamer_tex,
                output_dir=str(output_dir),
                template_dirs=[template_dir],
                images_dir=extract_result.images_dir,
                bib_content=bib_text if output_mode == OutputMode.FULL else "",
            )

            if not pdf_bytes:
                raise RuntimeError(
                    f"LaTeX compilation produced no PDF.\n\n{log_text}"
                )

            # Step 7: Package output ZIP
            await _update_job(session, job, JobStatus.COMPILING, 90)
            tex_path = output_dir / "presentation.tex"
            pdf_path_out = output_dir / "presentation.pdf"
            bib_path = output_dir / "references.bib"
            zip_path = output_dir / "presentation.zip"

            tex_path.write_text(beamer_tex, encoding="utf-8")
            pdf_path_out.write_bytes(pdf_bytes)
            if bib_text:
                bib_path.write_text(bib_text, encoding="utf-8")

            zip_files: dict[str, str | bytes] = {
                "presentation.tex": beamer_tex,
                "presentation.pdf": pdf_bytes,
                "build.log": log_text,
                "README.txt": _build_readme(document, output_mode),
            }
            if bib_text:
                zip_files["references.bib"] = bib_text

            img_files = collect_directory_files(
                extract_result.images_dir, prefix="images/"
            )
            zip_files.update(img_files)

            create_zip(zip_path, zip_files)

            # Complete
            job.status = JobStatus.COMPLETED
            job.progress_percent = 100
            job.output_zip_path = str(zip_path)
            job.output_tex_path = str(tex_path)
            job.output_pdf_path = str(pdf_path_out)
            job.output_bib_path = str(bib_path) if bib_text else None
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


def _build_readme(document, output_mode: OutputMode) -> str:
    return (
        f"Beamer presentation generated by paper2beamer\n"
        f"==============================================\n\n"
        f"Paper: {document.title}\n"
        f"Mode: {output_mode.value}\n"
        f"Sections: {len(document.sections)}\n"
        f"Citations detected: {len(document.citations)}\n\n"
        f"Files:\n"
        f"  - presentation.tex  : Beamer LaTeX source\n"
        f"  - presentation.pdf  : Compiled presentation\n"
        f"  - references.bib    : Extracted bibliography\n"
        f"  - build.log         : LaTeX compilation log\n"
        f"  - images/           : Extracted figures\n"
    )
