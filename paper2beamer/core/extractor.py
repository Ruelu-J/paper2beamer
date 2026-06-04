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
    """Uses the mineru-open-sdk to call the MinerU cloud API (token-based).

    On Windows + Python 3.10 the SSL handshake to cdn-mineru.openxlab.org.cn
    (the CDN that hosts extracted results) can fail with ``_ssl.c:1007``.
    We monkey-patch the SDK's download method to retry with ``verify=False``
    when that occurs — everything else (auth, upload, polling) hits
    mineru.net which works fine with normal SSL.
    """

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    # ------------------------------------------------------------------
    # SSL workaround for cdn-mineru.openxlab.org.cn download
    # ------------------------------------------------------------------

    @staticmethod
    def _patch_download_for_cdn_ssl():
        """Wrap ApiClient.download so it retries without SSL verification
        when the CDN host's certificate fails the handshake on Windows."""
        try:
            import mineru._api as _api_mod
        except ImportError:
            return None  # SDK not installed

        _orig_download = _api_mod.ApiClient.download

        def _ssl_safe_download(self, url: str) -> bytes:
            try:
                return _orig_download(self, url)
            except Exception as exc:
                err_str = str(exc).lower()
                if ('ssl' in err_str or '_ssl' in err_str
                        or 'connecterror' in err_str):
                    import httpx
                    import warnings
                    warnings.warn(
                        f"SSL handshake to CDN failed ({exc}), "
                        f"retrying with verify=False for download only.",
                        RuntimeWarning,
                    )
                    resp = httpx.get(
                        url,
                        timeout=httpx.Timeout(30.0, read=300.0),
                        follow_redirects=True,
                        verify=False,
                    )
                    resp.raise_for_status()
                    return resp.content
                raise

        _api_mod.ApiClient.download = _ssl_safe_download  # type: ignore[assignment]
        return _orig_download

    @staticmethod
    def _unpatch_download(orig):
        """Restore the original download method."""
        if orig is None:
            return
        try:
            import mineru._api as _api_mod
            _api_mod.ApiClient.download = orig  # type: ignore[assignment]
        except Exception:
            pass

    # ------------------------------------------------------------------
    # HTTP tracing (debug aid — can be removed once stable)
    # ------------------------------------------------------------------

    def _install_http_trace(self):
        """Monkey-patch httpx to trace every HTTP request made by mineru SDK."""
        try:
            import httpx as _httpx
        except ImportError:
            return

        _orig_send = _httpx.Client.send
        _trace_lines: list[str] = []

        def _patched_send(client_self, request, *args, **kwargs):
            _trace_lines.append(f"[TRACE] >>> {request.method} {request.url}")
            try:
                resp = _orig_send(client_self, request, *args, **kwargs)
                _trace_lines.append(
                    f"[TRACE] <<< {resp.status_code} "
                    f"(HTTP/{resp.http_version})"
                )
                return resp
            except Exception as exc:
                _trace_lines.append(
                    f"[TRACE] <<< EXCEPTION at {request.method} "
                    f"{request.url.host}: "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

        _httpx.Client.send = _patched_send  # type: ignore[assignment]

        import httpx as _httpx_module
        _orig_put = _httpx_module.put
        _orig_get = _httpx_module.get

        def _patched_put(url, *args, **kwargs):
            _trace_lines.append(f"[TRACE-PUT] >>> {url}")
            try:
                resp = _orig_put(url, *args, **kwargs)
                _trace_lines.append(f"[TRACE-PUT] <<< {resp.status_code}")
                return resp
            except Exception as exc:
                _trace_lines.append(
                    f"[TRACE-PUT] <<< EXCEPTION: {type(exc).__name__}: {exc}"
                )
                raise

        def _patched_get(url, *args, **kwargs):
            _trace_lines.append(f"[TRACE-GET] >>> {url}")
            try:
                resp = _orig_get(url, *args, **kwargs)
                _trace_lines.append(f"[TRACE-GET] <<< {resp.status_code}")
                return resp
            except Exception as exc:
                _trace_lines.append(
                    f"[TRACE-GET] <<< EXCEPTION: {type(exc).__name__}: {exc}"
                )
                raise

        _httpx_module.put = _patched_put  # type: ignore[assignment]
        _httpx_module.get = _patched_get  # type: ignore[assignment]

        self._trace_lines = _trace_lines
        self._orig_send = _orig_send
        self._orig_put = _orig_put
        self._orig_get = _orig_get

    def _uninstall_http_trace(self):
        """Restore original httpx functions."""
        try:
            import httpx as _httpx
            if hasattr(self, '_orig_send') and self._orig_send:
                _httpx.Client.send = self._orig_send
        finally:
            pass
        try:
            import httpx as _httpx_module
            if hasattr(self, '_orig_put') and self._orig_put:
                _httpx_module.put = self._orig_put
            if hasattr(self, '_orig_get') and self._orig_get:
                _httpx_module.get = self._orig_get
        finally:
            pass

    # ------------------------------------------------------------------
    # Main extraction entry point
    # ------------------------------------------------------------------

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

        # Work around Windows SSL issue when downloading results from
        # cdn-mineru.openxlab.org.cn (the API upload/poll uses mineru.net
        # which works fine).
        _orig_download = self._patch_download_for_cdn_ssl()
        self._install_http_trace()

        try:
            result = await asyncio.to_thread(
                client.extract,
                str(pdf_path),
                formula=True,
                table=True,
                timeout=600,
            )
        except Exception as exc:
            if hasattr(self, '_trace_lines') and self._trace_lines:
                print("=" * 60, flush=True)
                print("MinerU HTTP trace (last call failed):", flush=True)
                for line in self._trace_lines:
                    print(line, flush=True)
                print("=" * 60, flush=True)
            raise
        finally:
            self._uninstall_http_trace()
            self._unpatch_download(_orig_download)

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
