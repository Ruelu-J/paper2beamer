"""Upload endpoint — accepts PDF and starts conversion job."""

import uuid
import datetime
import asyncio
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from paper2beamer.api.dependencies import get_db
from paper2beamer.api.schemas import UploadResponse
from paper2beamer.config import settings
from paper2beamer.db.models import Job, JobStatus
from paper2beamer.core.hashing import hash_pdf
from paper2beamer.core.models import OutputMode

router = APIRouter()

MAX_PDF_SIZE = settings.max_upload_size_mb * 1024 * 1024


@router.post("/upload", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    mode: str = Form(default="full"),
    template_id: str | None = Form(default=None),
    bypass_cache: bool = Form(default=False),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")

    if mode not in ("abstract", "full"):
        raise HTTPException(400, "Mode must be 'abstract' or 'full'.")

    from paper2beamer.db.database import get_session_factory

    content = await file.read()
    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(
            413,
            f"File too large. Maximum is {settings.max_upload_size_mb}MB.",
        )

    job_id = str(uuid.uuid4())

    pdf_dir = Path(settings.data_dir) / "uploads"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / f"{job_id}.pdf"
    pdf_path.write_bytes(content)

    pdf_hash = hash_pdf(bytes(content))

    session_factory = get_session_factory()
    async with session_factory() as session:
        job = Job(
            id=job_id,
            status=JobStatus.PENDING,
            mode=mode,
            template_id=template_id,
            pdf_filename=file.filename,
            pdf_hash=pdf_hash,
            created_at=datetime.datetime.utcnow(),
        )
        session.add(job)
        await session.commit()

    from paper2beamer.worker.tasks import process_job

    asyncio.create_task(
        process_job(
            job_id=job_id,
            pdf_path=str(pdf_path),
            mode=mode,
            session_factory=session_factory,
            template_id=template_id,
            bypass_cache=bypass_cache,
        )
    )

    return UploadResponse(
        job_id=job_id,
        status=JobStatus.PENDING.value,
        message="PDF queued for processing.",
    )
