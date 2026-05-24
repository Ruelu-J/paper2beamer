"""Template management endpoints."""

import uuid
import datetime
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from paper2beamer.api.dependencies import get_db
from paper2beamer.api.schemas import (
    TemplateInfo, TemplateListResponse, TemplateInstallResponse, MessageResponse,
)
from paper2beamer.db.models import UserTemplate
from paper2beamer.core.templates import TemplateManager, TemplateValidationError
from paper2beamer.config import settings

router = APIRouter()


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates():
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(UserTemplate).order_by(UserTemplate.created_at.desc())
        result = await session.execute(stmt)
        entries = result.scalars().all()

        templates = [
            TemplateInfo(
                id=t.id,
                name=t.name,
                description=t.description,
                is_default=bool(t.is_default),
                created_at=t.created_at,
            )
            for t in entries
        ]

        default_exists = any(t.is_default for t in templates)
        if not default_exists:
            templates.insert(0, TemplateInfo(
                id="default",
                name="Default Theme",
                description="Built-in minimal Beamer theme",
                is_default=True,
            ))

        return TemplateListResponse(templates=templates)


@router.post("/templates/upload", response_model=TemplateInstallResponse)
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str | None = Form(default=None),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Only ZIP files are accepted.")

    content = await file.read()
    tmp_path = Path(settings.data_dir) / "uploads" / f"template_{uuid.uuid4()}.zip"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(content)

    try:
        mgr = TemplateManager(settings.template_dir)
        template_id = mgr.install(str(tmp_path), name, description or "")

        from paper2beamer.db.database import get_session_factory
        session_factory = get_session_factory()
        async with session_factory() as session:
            tmpl = UserTemplate(
                id=template_id,
                name=name,
                description=description,
                directory=str(Path(settings.template_dir) / template_id),
                created_at=datetime.datetime.utcnow(),
            )
            session.add(tmpl)
            await session.commit()

        return TemplateInstallResponse(
            template_id=template_id,
            name=name,
            message="Template installed successfully.",
        )
    except TemplateValidationError as e:
        raise HTTPException(400, str(e))
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@router.delete("/templates/{template_id}", response_model=MessageResponse)
async def delete_template(template_id: str):
    if template_id == "default":
        raise HTTPException(400, "Cannot delete the default template.")

    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        tmpl = await session.get(UserTemplate, template_id)
        if not tmpl:
            raise HTTPException(404, "Template not found.")

        mgr = TemplateManager(settings.template_dir)
        mgr.delete(template_id)

        await session.delete(tmpl)
        await session.commit()

    return MessageResponse(message="Template deleted.")
