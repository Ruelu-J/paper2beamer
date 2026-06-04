"""SQLAlchemy database models and async engine setup."""

import datetime
import uuid
from sqlalchemy import Column, String, DateTime, Integer, Text, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import enum


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CONVERTING = "converting"
    COMPILING = "compiling"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(SAEnum(JobStatus), default=JobStatus.PENDING)
    mode = Column(String(10))
    template_id = Column(String(36), nullable=True)
    pdf_filename = Column(String(255))
    pdf_hash = Column(String(64))
    output_zip_path = Column(String(512), nullable=True)
    output_tex_path = Column(String(512), nullable=True)
    output_pdf_path = Column(String(512), nullable=True)
    output_bib_path = Column(String(512), nullable=True)
    log_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    step_log = Column(Text, nullable=True)  # JSON list of {time, step, detail}
    progress_percent = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class CacheEntry(Base):
    __tablename__ = "cache_entries"

    hash = Column(String(64), primary_key=True)
    pdf_filename = Column(String(255))
    markdown_path = Column(String(512))
    images_dir = Column(String(512))
    json_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_accessed = Column(DateTime, default=datetime.datetime.utcnow)
    size_bytes = Column(Integer, default=0)


class UserTemplate(Base):
    __tablename__ = "user_templates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(128))
    description = Column(Text, nullable=True)
    directory = Column(String(512))
    is_default = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
