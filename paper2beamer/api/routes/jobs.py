"""Job status and download endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from paper2beamer.api.dependencies import get_db
from paper2beamer.api.schemas import JobStatusResponse
from paper2beamer.db.models import Job

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found.")

        return JobStatusResponse(
            job_id=job.id,
            status=job.status.value if job.status else "unknown",
            mode=job.mode,
            pdf_filename=job.pdf_filename,
            pdf_hash=job.pdf_hash,
            progress_percent=job.progress_percent or 0,
            error_message=job.error_message,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )


@router.get("/jobs/{job_id}/download")
async def download_result(job_id: str):
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found.")

        if job.status.value != "completed":
            raise HTTPException(409, "Job is not yet completed.")

        if not job.output_zip_path:
            raise HTTPException(404, "Output file not found.")

        return FileResponse(
            path=job.output_zip_path,
            filename="presentation.zip",
            media_type="application/zip",
        )
