"""Filesystem + DB-based cache manager for PDF extraction results."""

import json
import shutil
import datetime
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from paper2beamer.core.models import ExtractResult
from paper2beamer.db.models import CacheEntry


class CacheManager:
    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, pdf_hash: str) -> Path:
        prefix = pdf_hash[:2]
        return self.cache_dir / prefix / pdf_hash

    async def has(self, session: AsyncSession, pdf_hash: str) -> bool:
        stmt = select(CacheEntry).where(CacheEntry.hash == pdf_hash)
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        cache_path = self._cache_path(pdf_hash)
        if not (cache_path / "output.md").exists():
            return False
        return True

    async def get(
        self, session: AsyncSession, pdf_hash: str
    ) -> ExtractResult | None:
        stmt = select(CacheEntry).where(CacheEntry.hash == pdf_hash)
        result = await session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry is None:
            return None
        cache_path = self._cache_path(pdf_hash)
        md_path = cache_path / "output.md"
        if not md_path.exists():
            return None
        entry.last_accessed = datetime.datetime.utcnow()
        await session.commit()
        markdown = md_path.read_text(encoding="utf-8")
        images_dir = str(cache_path / "images")
        json_path = str(cache_path / "metadata.json")
        return ExtractResult(
            markdown=markdown,
            images_dir=images_dir,
            json_path=json_path,
            pdf_hash=pdf_hash,
        )

    async def put(
        self,
        session: AsyncSession,
        pdf_hash: str,
        extract_result: ExtractResult,
        pdf_filename: str,
    ):
        cache_path = self._cache_path(pdf_hash)
        if cache_path.exists():
            shutil.rmtree(cache_path)
        cache_path.mkdir(parents=True, exist_ok=True)

        md_dest = cache_path / "output.md"
        md_dest.write_text(extract_result.markdown, encoding="utf-8")

        images_src = Path(extract_result.images_dir)
        images_dest = cache_path / "images"
        if images_src.exists() and images_src != images_dest:
            if images_dest.exists():
                shutil.rmtree(images_dest)
            shutil.copytree(images_src, images_dest)

        if extract_result.json_path:
            json_src = Path(extract_result.json_path)
            if json_src.exists():
                shutil.copy2(json_src, cache_path / "metadata.json")

        total_size = sum(
            f.stat().st_size for f in cache_path.rglob("*") if f.is_file()
        )

        entry = CacheEntry(
            hash=pdf_hash,
            pdf_filename=pdf_filename,
            markdown_path=str(md_dest),
            images_dir=str(images_dest),
            json_path=str(cache_path / "metadata.json"),
            created_at=datetime.datetime.utcnow(),
            last_accessed=datetime.datetime.utcnow(),
            size_bytes=total_size,
        )
        session.add(entry)
        await session.commit()

    async def evict_oldest(self, session: AsyncSession, keep_count: int = 100):
        stmt = (
            select(CacheEntry)
            .order_by(CacheEntry.last_accessed.asc())
        )
        result = await session.execute(stmt)
        entries = result.scalars().all()
        to_remove = entries[:-keep_count] if len(entries) > keep_count else []
        for entry in to_remove:
            cache_path = self._cache_path(entry.hash)
            if cache_path.exists():
                shutil.rmtree(cache_path)
            await session.delete(entry)
        if to_remove:
            await session.commit()

    async def clear(self, session: AsyncSession):
        stmt = select(CacheEntry)
        result = await session.execute(stmt)
        entries = result.scalars().all()
        for entry in entries:
            cache_path = self._cache_path(entry.hash)
            if cache_path.exists():
                shutil.rmtree(cache_path)
            await session.delete(entry)
        await session.commit()

    async def list_entries(self, session: AsyncSession) -> list[dict]:
        stmt = select(CacheEntry).order_by(CacheEntry.last_accessed.desc())
        result = await session.execute(stmt)
        entries = result.scalars().all()
        return [
            {
                "hash": e.hash,
                "pdf_filename": e.pdf_filename,
                "size_bytes": e.size_bytes,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "last_accessed": e.last_accessed.isoformat() if e.last_accessed else None,
            }
            for e in entries
        ]
