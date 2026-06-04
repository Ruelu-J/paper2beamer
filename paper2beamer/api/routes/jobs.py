"""Job status and download endpoints."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select

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


@router.get("/jobs/{job_id}/html")
async def get_job_status_html(request: Request, job_id: str):
    """Return HTML fragment for htmx polling."""
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return HTMLResponse(
                '<div class="error-msg">Job not found.</div>', status_code=404
            )

        status_val = job.status.value if job.status else "unknown"
        progress = job.progress_percent or 0
        pdf_name = job.pdf_filename or "unknown.pdf"
        mode = job.mode or "full"

        status_class = status_val
        status_label = status_val.replace("_", " ")

        if status_val == "completed":
            download_url = f"/api/jobs/{job_id}/download"
            return HTMLResponse(f"""<div class="job-card completed" id="result-area">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge completed">{status_label}</span>
    </div>
    <div class="progress-bar"><div class="progress-fill" style="width:100%"></div></div>
    <a href="{download_url}" class="download-btn" download>Download ZIP</a>
</div>""")

        if status_val == "failed":
            error = job.error_message or "Unknown error"
            return HTMLResponse(f"""<div class="job-card failed" id="result-area">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge failed">failed</span>
    </div>
    <div class="error-msg">{error}</div>
</div>""")

        # In progress
        stage_labels = {
            "pending": "queued",
            "extracting": "Extracting PDF content...",
            "converting": "Converting to Beamer LaTeX...",
            "compiling": "Compiling PDF...",
            "packaging": "Creating ZIP...",
        }
        stage_text = stage_labels.get(status_val, status_label)

        progress_stops = {"pending": 5, "extracting": 30, "converting": 60,
                          "compiling": 85, "packaging": 95}

        # Stop polling when done
        stop_polling = ""
        if status_val in ("completed", "failed"):
            stop_polling = " every 2s"  # keep polling until complete, handled above

        return HTMLResponse(f"""<div class="job-card" id="result-area"
    hx-get="/api/jobs/{job_id}/html"
    hx-trigger="every 2s"
    hx-swap="innerHTML">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge {status_class}">{status_label}</span>
    </div>
    <div class="progress-bar">
        <div class="progress-fill" style="width:{progress_stops.get(status_val, progress)}%"></div>
    </div>
    <p style="font-size:0.85rem;color:#888;">{stage_text}</p>
</div>""")


@router.get("/jobs/recent")
async def get_recent_jobs():
    """Return HTML fragment listing recent jobs."""
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Job).order_by(Job.created_at.desc()).limit(10)
        result = await session.execute(stmt)
        jobs = result.scalars().all()

        if not jobs:
            return HTMLResponse("")

        items = []
        for job in jobs:
            status_val = job.status.value if job.status else "unknown"
            status_class = "completed" if status_val == "completed" else (
                "failed" if status_val == "failed" else "pending"
            )
            time_str = job.created_at.strftime("%Y-%m-%d %H:%M") if job.created_at else ""
            name = job.pdf_filename or "unknown.pdf"
            items.append(f"""<div class="job-history-item">
    <span class="name">{name}</span>
    <span class="status-badge {status_class}">{status_val}</span>
    <span class="time">{time_str}</span>
</div>""")

        return HTMLResponse(
            '<h2>Recent Jobs</h2>\n' + "\n".join(items)
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
