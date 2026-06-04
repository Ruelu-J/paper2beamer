"""End-to-end test: drives worker.process_job exactly like the web API
would. Verifies the new compile_and_fix loop runs and produces a clean
build.log + presentation.pdf + presentation.zip.

Run: python test_e2e.py
Outputs land in e2e_output/<job_id>/.
"""
import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Put MiKTeX on PATH so latexmk is found.
os.environ['PATH'] = (
    'C:/Users/17576/AppData/Local/Programs/MiKTeX/miktex/bin/x64;'
    + os.environ.get('PATH', '')
)

# Redirect output dir so we can keep this run separate.
os.environ['OUTPUT_DIR'] = './e2e_output'

from paper2beamer.config import settings
from paper2beamer.db.database import init_db, get_session_factory
from paper2beamer.db.models import Job, JobStatus
from paper2beamer.worker.tasks import process_job


TEMPLATE_ID = "c0479bae-2779-4fae-91e6-3206f027ee8e"  # SUDA, just installed
PDF_PATH = "pdf/2309.02211v5.pdf"
MODE = "full"


async def main():
    Path('./e2e_output').mkdir(parents=True, exist_ok=True)
    await init_db()

    job_id = str(uuid.uuid4())
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = Job(
            id=job_id,
            pdf_filename=Path(PDF_PATH).name,
            mode=MODE,
            template_id=TEMPLATE_ID,
            status=JobStatus.PENDING,
            progress_percent=0,
        )
        session.add(job)
        await session.commit()

    print(f"=== Job {job_id} ===", flush=True)
    print(f"PDF: {PDF_PATH}", flush=True)
    print(f"Mode: {MODE}", flush=True)
    print(f"Template: SUDA ({TEMPLATE_ID})", flush=True)
    print(f"LLM model: {settings.llm_model}", flush=True)
    print(f"LLM_FIX_ATTEMPTS: {settings.llm_fix_attempts}", flush=True)
    print(f"TEX_ENGINE: {settings.tex_engine}", flush=True)
    print(f"Output dir: {settings.output_dir}/{job_id}", flush=True)
    print("=" * 60, flush=True)

    await process_job(
        job_id=job_id,
        pdf_path=PDF_PATH,
        mode=MODE,
        session_factory=None,  # process_job re-acquires the factory itself
        template_id=TEMPLATE_ID,
        bypass_cache=False,
    )

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        print("=" * 60, flush=True)
        print(f"Final status: {job.status}", flush=True)
        print(f"Progress: {job.progress_percent}%", flush=True)
        if job.error_message:
            print(f"Error: {job.error_message[:500]}", flush=True)
        print(f"Output ZIP: {job.output_zip_path}", flush=True)
        print(f"Output PDF: {job.output_pdf_path}", flush=True)
        print(f"Output TEX: {job.output_tex_path}", flush=True)

    out_dir = Path('./e2e_output') / job_id
    if out_dir.exists():
        print("\n=== Output directory contents ===", flush=True)
        for f in sorted(out_dir.iterdir()):
            try:
                size = f.stat().st_size
                print(f"  {f.name}: {size:,} bytes", flush=True)
            except OSError:
                print(f"  {f.name}: (no stat)", flush=True)

    # Inspect build.log for compile errors
    log_file = None
    for cand in ['build.log', 'main.log']:
        p = out_dir / cand
        if p.exists():
            log_file = p
            break
    if log_file:
        log_text = log_file.read_text(encoding='utf-8', errors='replace')
        err_lines = [l for l in log_text.splitlines() if l.startswith('!')]
        warn_count = sum(
            1 for l in log_text.splitlines()
            if 'Warning' in l or 'warning' in l
        )
        print(f"\n=== {log_file.name} summary ===", flush=True)
        print(f"  Total lines: {len(log_text.splitlines()):,}", flush=True)
        print(f"  Lines starting with '!': {len(err_lines)}", flush=True)
        print(f"  Warning lines: {warn_count}", flush=True)
        if err_lines:
            print("  Sample errors:", flush=True)
            for e in err_lines[:10]:
                print(f"    {e[:200]}", flush=True)
        else:
            print("  No '!' error lines.", flush=True)


asyncio.run(main())
