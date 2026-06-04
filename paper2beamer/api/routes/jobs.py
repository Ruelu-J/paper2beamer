"""Job status and download endpoints."""

import json
import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select

from paper2beamer.api.schemas import JobStatusResponse
from paper2beamer.db.models import Job

router = APIRouter()

# ------------------------------------------------------------------
# Human-friendly labels for each pipeline step
# ------------------------------------------------------------------
STEP_LABELS: dict[str, str] = {
    "checking_cache":     "Checking cache",
    "cache_hit":          "Found cached extraction",
    "cache_miss":         "Cache miss — running extraction",
    "extracting_uploading": "Uploading PDF to MinerU",
    "extracting_done":    "Extraction complete",
    "parsing_markdown":   "Parsing markdown",
    "parsing_done":       "Document structured",
    "converting_llm":     "Generating Beamer (LLM)",
    "converting_programmatic": "Generating Beamer",
    "converting_done":    "LaTeX generated",
    "compiling_latex":    "Compiling PDF",
    "packaging_zip":      "Creating ZIP archive",
    "done":               "Done",
}

# Steps that mark a completed phase (display checkmark, not a spinner)
CHECKPOINT_STEPS = {
    "cache_hit", "extracting_done", "parsing_done",
    "converting_done", "done",
}

# Final pipeline steps that should appear even if not yet reached
ALL_PIPELINE_STEPS = [
    "checking_cache",
    "extracting_uploading",
    "parsing_markdown",
    "converting_llm",
    "converting_programmatic",
    "compiling_latex",
    "packaging_zip",
    "done",
]


def _parse_step_log(step_log_raw: str | None) -> list[dict]:
    """Return parsed step-log list, or empty list on parse failure."""
    if not step_log_raw:
        return []
    try:
        return json.loads(step_log_raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _elapsed(start: datetime.datetime | None,
              end: datetime.datetime | None = None) -> str:
    """Human-friendly elapsed time string."""
    if not start:
        return ""
    finish = end or datetime.datetime.utcnow()
    delta = finish - start
    if delta.total_seconds() < 0:
        return ""
    total_s = int(delta.total_seconds())
    if total_s < 60:
        return f"{total_s}s"
    mins = total_s // 60
    secs = total_s % 60
    return f"{mins}m {secs}s"


def _render_step_timeline(steps: list[dict],
                           is_failed: bool = False) -> str:
    """Render a vertical step timeline as HTML."""
    if not steps:
        return ""

    lines: list[str] = ['<ul class="step-timeline">']
    last_idx = len(steps) - 1

    for i, s in enumerate(steps):
        step_key = s.get("step", "")
        detail = s.get("detail", "")
        step_time = s.get("time", "")
        label = STEP_LABELS.get(step_key, detail or step_key.replace("_", " "))

        is_last = (i == last_idx)

        if step_key in CHECKPOINT_STEPS or (not is_last):
            # Completed step
            icon = '<span class="step-icon done">&#10003;</span>'
            css = "step-done"
        elif is_failed and is_last:
            # Failed on this step
            icon = '<span class="step-icon failed">&#10007;</span>'
            css = "step-failed"
        else:
            # Active / in-progress step
            icon = '<span class="step-icon active"><span class="spinner"></span></span>'
            css = "step-active"

        lines.append(
            f'<li class="{css}">{icon}'
            f'<span class="step-label">{label}</span>'
            f'<span class="step-time">{step_time}</span>'
            f'</li>'
        )
    lines.append('</ul>')
    return "\n".join(lines)


# ------------------------------------------------------------------
# JSON endpoint
# ------------------------------------------------------------------

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
            step_log=job.step_log,
            output_tex_path=job.output_tex_path,
            log_text=job.log_text,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )


# ------------------------------------------------------------------
# HTML fragment endpoint (htmx polling target)
# ------------------------------------------------------------------

@router.get("/jobs/{job_id}/html")
async def get_job_status_html(request: Request, job_id: str):
    """Return HTML fragment — step timeline + progress bar + error details."""
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if not job:
            return HTMLResponse(
                '<div class="error-msg">Job not found.</div>', status_code=404
            )

        status_val: str = job.status.value if job.status else "unknown"
        progress: int = job.progress_percent or 0
        pdf_name: str = job.pdf_filename or "unknown.pdf"
        mode: str = job.mode or "full"
        steps = _parse_step_log(job.step_log)
        elapsed_str = _elapsed(job.created_at, job.completed_at)

        status_label = status_val.replace("_", " ")
        is_terminal = status_val in ("completed", "failed")

        # --- COMPLETED ---
        if status_val == "completed":
            timeline = _render_step_timeline(steps)
            download_url = f"/api/jobs/{job_id}/download"
            return HTMLResponse(f"""<div class="job-card completed" id="result-area">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge completed">{status_label}</span>
        <span class="elapsed-time">&#9202; {elapsed_str}</span>
    </div>
    <div class="progress-bar">
        <div class="progress-fill" style="width:100%"></div>
    </div>
    {timeline}
    <a href="{download_url}" class="download-btn" download>&#10515; Download ZIP</a>
</div>""")

        # --- FAILED ---
        if status_val == "failed":
            error = job.error_message or "Unknown error"
            # Mark the last step as failed for rendering
            if steps:
                steps[-1]["_failed"] = True
            timeline = _render_step_timeline(steps, is_failed=True)

            # Collapsible build log
            log_section = ""
            if job.log_text:
                # Truncate for display; full content in details
                log_preview = job.log_text[-3000:]
                log_section = f"""
    <details class="error-details">
        <summary>Build log (last 3000 chars)</summary>
        <pre>{_escape_html(log_preview)}</pre>
    </details>"""

            tex_hint = ""
            if job.output_tex_path:
                tex_hint = (f'<p class="tex-hint">Inspect .tex: '
                            f'<code>{_escape_html(job.output_tex_path)}</code></p>')

            return HTMLResponse(f"""<div class="job-card failed" id="result-area">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge failed">failed</span>
        <span class="elapsed-time">&#9202; {elapsed_str}</span>
    </div>
    <div class="error-msg">
        <strong>Error:</strong> {_escape_html(error)}
    </div>
    {timeline}
    {tex_hint}
    {log_section}
</div>""")

        # --- IN PROGRESS ---
        # Use the ACTUAL progress_percent value from DB, not hardcoded stops
        timeline = _render_step_timeline(steps)
        # Show elapsed time (updates each poll)
        elapsed_str = _elapsed(job.created_at)

        # Choose a one-line stage description from the last step, or fallback
        if steps:
            last_detail = steps[-1].get("detail", "")
            stage_text = last_detail or STEP_LABELS.get(
                steps[-1].get("step", ""), "Processing..."
            )
        else:
            stage_text = "Queued..."

        return HTMLResponse(f"""<div class="job-card" id="result-area"
    hx-get="/api/jobs/{job_id}/html"
    hx-trigger="every 2s"
    hx-swap="innerHTML">
    <h3>{pdf_name}</h3>
    <div class="job-meta">
        <span>Mode: {mode}</span>
        <span class="status-badge {status_val}">{status_label}</span>
        <span class="elapsed-time">&#9202; {elapsed_str}</span>
    </div>
    <div class="progress-bar">
        <div class="progress-fill" style="width:{progress}%"></div>
    </div>
    <p class="stage-text">{stage_text}</p>
    {timeline}
</div>""")


# ------------------------------------------------------------------
# Recent jobs
# ------------------------------------------------------------------

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
    <span class="name">{_escape_html(name)}</span>
    <span class="status-badge {status_class}">{status_val}</span>
    <span class="time">{time_str}</span>
</div>""")

        return HTMLResponse(
            '<h2>Recent Jobs</h2>\n' + "\n".join(items)
        )


# ------------------------------------------------------------------
# Download
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
