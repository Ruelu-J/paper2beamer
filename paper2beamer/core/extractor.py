"""MinerU PDF extractor abstraction layer."""

import asyncio
import json
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from paper2beamer.core.models import ExtractResult
from paper2beamer.core.hashing import hash_pdf


class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, pdf_path: str | Path, output_dir: str | Path) -> ExtractResult:
        ...


class MinerUCliExtractor(BaseExtractor):
    """Uses the `mineru` CLI command to extract PDF content."""

    def __init__(self, timeout: int = 300):
        self.timeout = timeout

    async def extract(self, pdf_path: str | Path, output_dir: str | Path) -> ExtractResult:
        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_hash = hash_pdf(pdf_path)

        cmd = ["mineru", "-p", str(pdf_path), "-o", str(output_dir)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(
                f"MinerU extraction timed out after {self.timeout}s. "
                "Try a smaller PDF or increase MINERU_TIMEOUT."
            )

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"MinerU extraction failed: {err_msg}")

        return self._collect_output(output_dir, pdf_hash)

    def _collect_output(self, output_dir: Path, pdf_hash: str) -> ExtractResult:
        actual_dir = output_dir
        for d in sorted(output_dir.iterdir(), key=lambda x: x.name):
            if d.is_dir() and d.name != "images":
                actual_dir = d
                break

        markdown_files = list(actual_dir.glob("**/*.md"))
        markdown = ""
        if markdown_files:
            markdown = markdown_files[0].read_text(encoding="utf-8")

        images_dir = actual_dir / "images"
        if not images_dir.exists():
            images_dir = actual_dir

        json_path = ""
        json_files = list(actual_dir.glob("**/*.json"))
        if json_files:
            json_path = str(json_files[0])

        return ExtractResult(
            markdown=markdown,
            images_dir=str(images_dir),
            json_path=json_path,
            pdf_hash=pdf_hash,
        )


class LocalMinerUExtractor(BaseExtractor):
    """Calls a local mineru-api FastAPI server."""

    def __init__(self, api_url: str = "http://localhost:8001", timeout: int = 300):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    async def extract(self, pdf_path: str | Path, output_dir: str | Path) -> ExtractResult:
        import aiohttp
        import aiofiles

        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_hash = hash_pdf(pdf_path)

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = aiohttp.FormData()
            async with aiofiles.open(pdf_path, "rb") as f:
                file_data = await f.read()
            data.add_field("file", file_data, filename=pdf_path.name)
            async with session.post(
                f"{self.api_url}/file_parse", data=data
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(
                        f"MinerU API returned {resp.status}: {text}"
                    )
                result = await resp.json()

        markdown = self._extract_markdown_from_api_result(result)
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)

        return ExtractResult(
            markdown=markdown,
            images_dir=str(images_dir),
            json_path=str(output_dir / "result.json"),
            pdf_hash=pdf_hash,
            metadata={"api_result": result},
        )

    def _extract_markdown_from_api_result(self, result: dict) -> str:
        if "markdown" in result:
            return result["markdown"]
        if "content" in result:
            return result["content"]
        return json.dumps(result, indent=2)


class CloudMinerUExtractor(BaseExtractor):
    """Uses the mineru-open-sdk to call the MinerU cloud API (token-based)."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def extract(self, pdf_path: str | Path, output_dir: str | Path) -> ExtractResult:
        try:
            from mineru import MinerU
        except ImportError:
            raise ImportError(
                "mineru-open-sdk is required for cloud mode. "
                "Install with: pip install mineru-open-sdk"
            )

        pdf_path = Path(pdf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_hash = hash_pdf(pdf_path)

        client = MinerU(self.api_key) if self.api_key else MinerU()

        # Use token-based extract (not flash_extract) for reliable results
        result = await asyncio.to_thread(
            client.extract,
            str(pdf_path),
            formula=True,
            table=True,
            timeout=600,
        )

        if result.state != "done":
            error_msg = result.error or f"state={result.state}"
            raise RuntimeError(
                f"MinerU cloud extraction failed: {error_msg}. "
                f"err_code={result.err_code}"
            )

        if not result.markdown:
            raise RuntimeError(
                "MinerU cloud extraction returned no markdown content."
            )

        md_path = output_dir / "output.md"
        result.save_markdown(str(md_path), with_images=True)

        images_dir = output_dir / "images"
        if not images_dir.exists():
            images_dir = output_dir

        return ExtractResult(
            markdown=result.markdown,
            images_dir=str(images_dir),
            json_path="",
            pdf_hash=pdf_hash,
        )


def create_extractor(mode: str = "local", api_url: str = "", api_key: str = "",
                     timeout: int = 300) -> BaseExtractor:
    if mode == "cloud":
        return CloudMinerUExtractor(api_key=api_key)
    if mode == "cli":
        return MinerUCliExtractor(timeout=timeout)
    return LocalMinerUExtractor(api_url=api_url, timeout=timeout)
