"""Command-line interface for paper2beamer."""

import asyncio
import datetime
import sys
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from paper2beamer.config import settings
from paper2beamer.core.models import OutputMode
from paper2beamer.core.hashing import hash_pdf
from paper2beamer.core.extractor import create_extractor
from paper2beamer.core.parser import MarkdownParser
from paper2beamer.core.converter import BeamerConverter
from paper2beamer.core.splitter import FrameSplitter
from paper2beamer.core.compiler import LatexCompiler
from paper2beamer.core.citations import CitationDetector
from paper2beamer.core.templates import TemplateManager, TemplateValidationError
from paper2beamer.cache.manager import CacheManager
from paper2beamer.db.database import init_db, get_session_factory
from paper2beamer.utils.file_utils import create_zip, collect_directory_files

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """paper2beamer — Convert math/statistics papers into Beamer presentations."""


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--mode", "-m", type=click.Choice(["abstract", "full"]),
              default="full", help="Output mode")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output ZIP path (default: <pdf_name>_beamer.zip)")
@click.option("--template", "-t", type=click.Path(exists=True), default=None,
              help="Beamer template ZIP file")
@click.option("--mineru-mode", type=click.Choice(["local", "cli", "cloud"]),
              default=None, help="MinerU mode (overrides env)")
@click.option("--mineru-key", default=None, help="MinerU cloud API key")
@click.option("--mineru-url", default=None, help="MinerU local API URL")
@click.option("--no-cache", is_flag=True, help="Bypass cache")
def convert(pdf_path, mode, output, template, mineru_mode, mineru_key, mineru_url,
            no_cache):
    """Convert a PDF paper to a Beamer presentation."""
    pdf_path = Path(pdf_path).resolve()

    if output is None:
        output = pdf_path.parent / f"{pdf_path.stem}_beamer.zip"
    else:
        output = Path(output)

    async def _run():
        await init_db()

        # Setup
        mmode = mineru_mode or settings.mineru_mode
        mkey = mineru_key or settings.mineru_api_key
        murl = mineru_url or settings.mineru_api_url

        extractor = create_extractor(
            mode=mmode, api_url=murl, api_key=mkey,
            timeout=settings.mineru_timeout,
        )
        parser = MarkdownParser()
        converter = BeamerConverter()
        splitter = FrameSplitter()
        compiler = LatexCompiler(
            engine=settings.tex_engine,
            timeout=settings.latex_timeout,
        )
        citation_detector = CitationDetector()
        cache_mgr = CacheManager(settings.cache_dir)
        output_mode = OutputMode(mode)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:

            # Step 1: Hash + Cache lookup
            task = progress.add_task("Computing PDF hash...", total=None)
            pdf_hash = hash_pdf(pdf_path)
            progress.update(task, description=f"PDF hash: {pdf_hash[:16]}...")

            extract_result = None
            if not no_cache:
                session_factory = get_session_factory()
                async with session_factory() as session:
                    has = await cache_mgr.has(session, pdf_hash)
                    if has:
                        progress.update(task, description="Cache hit! Loading cached extraction...")
                        extract_result = await cache_mgr.get(session, pdf_hash)

            # Step 2: Extract with MinerU
            if extract_result is None:
                task = progress.add_task("Extracting PDF with MinerU...", total=None)
                output_dir = Path(settings.output_dir) / str(uuid.uuid4())
                output_dir.mkdir(parents=True, exist_ok=True)
                extract_result = await extractor.extract(pdf_path, output_dir)

                session_factory = get_session_factory()
                async with session_factory() as session:
                    await cache_mgr.put(
                        session, pdf_hash, extract_result, pdf_path.name
                    )
                progress.update(task, description="Extraction complete!")

            if not extract_result.markdown.strip():
                console.print("[red]Error: Extracted markdown is empty. The PDF may be scanned or corrupted.[/red]")
                return

            # Step 3: Parse
            task = progress.add_task("Parsing document structure...", total=None)
            document = parser.parse(extract_result.markdown, extract_result.images_dir)
            progress.update(task, description=f"Parsed: {document.title[:60]}...")

            # Step 4: Citations
            task = progress.add_task("Extracting citations...", total=None)
            citations, bib_text = citation_detector.extract(document)
            progress.update(task, description=f"Found {len(citations)} citations")

            # Step 5: Convert to Beamer
            task = progress.add_task("Converting to Beamer...", total=None)
            template_dir = ""
            if template:
                mgr = TemplateManager(settings.template_dir)
                template_dir = mgr.install(template, f"cli-template-{uuid.uuid4().hex[:8]}")
            if not template_dir:
                template_dir = str(
                    Path(__file__).parent.parent.parent / "templates" / "default"
                )

            beamer_tex = converter.convert(document, template_dir, output_mode)
            progress.update(task, description="Beamer LaTeX generated")

            # Step 6: Split frames
            task = progress.add_task("Splitting frames...", total=None)
            beamer_tex = splitter.split(beamer_tex)

            # Step 7: Compile
            task = progress.add_task("Compiling LaTeX...", total=None)
            compile_dir = Path(settings.output_dir) / "compile" / str(uuid.uuid4())
            compile_dir.mkdir(parents=True, exist_ok=True)

            pdf_bytes, log_text = await compiler.compile(
                tex_content=beamer_tex,
                output_dir=str(compile_dir),
                template_dirs=[template_dir],
                images_dir=extract_result.images_dir,
                bib_content=bib_text if output_mode == OutputMode.FULL else "",
            )

            if not pdf_bytes:
                console.print("[red]LaTeX compilation failed![/red]")
                console.print(log_text[-2000:])
                return

            progress.update(task, description=f"Compilation successful! ({len(pdf_bytes):,} bytes)")

            # Step 8: Package ZIP
            task = progress.add_task("Packaging output ZIP...", total=None)
            zip_files: dict[str, str | bytes] = {
                "presentation.tex": beamer_tex,
                "presentation.pdf": pdf_bytes,
                "build.log": log_text,
                "README.txt": (
                    f"Beamer presentation generated by paper2beamer\n"
                    f"Paper: {document.title}\n"
                    f"Mode: {mode}\n"
                    f"Sections: {len(document.sections)}\n"
                ),
            }
            if bib_text:
                zip_files["references.bib"] = bib_text
            img_files = collect_directory_files(extract_result.images_dir, prefix="images/")
            zip_files.update(img_files)

            create_zip(output, zip_files)

        console.print(f"\n[green]Done![/green] Output: [bold]{output}[/bold]")
        console.print(f"  Title: {document.title}")
        console.print(f"  Authors: {', '.join(document.authors[:3])}")
        console.print(f"  Sections: {len(document.sections)}")
        console.print(f"  Citations: {len(citations)}")

    asyncio.run(_run())


@cli.command()
@click.option("--host", default=None, help="Host to bind")
@click.option("--port", default=None, type=int, help="Port to bind")
def serve(host, port):
    """Start the web server."""
    import uvicorn
    h = host or settings.host
    p = port or settings.port
    console.print(f"[green]Starting paper2beamer server at http://{h}:{p}[/green]")
    uvicorn.run(
        "paper2beamer.api.app:create_app",
        host=h, port=p, factory=True,
    )


@cli.command()
def worker():
    """Start a background worker (placeholder for future Celery/arq worker)."""
    console.print("[yellow]Worker mode not yet implemented. Use the embedded task runner.[/yellow]")


@cli.group()
def template():
    """Manage Beamer templates."""


@template.command("install")
@click.argument("zip_path", type=click.Path(exists=True))
@click.option("--name", "-n", required=True, help="Template name")
def template_install(zip_path, name):
    """Install a Beamer template from a ZIP file."""
    mgr = TemplateManager(settings.template_dir)
    try:
        tid = mgr.install(zip_path, name)
        console.print(f"[green]Template installed: {name} (id: {tid})[/green]")
    except TemplateValidationError as e:
        console.print(f"[red]Error: {e}[/red]")


@template.command("list")
def template_list():
    """List installed templates."""
    mgr = TemplateManager(settings.template_dir)
    templates = mgr.list_local()

    table = Table(title="Installed Templates")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("STY Files")

    for t in templates:
        table.add_row(t["id"], t.get("name", "-"), str(t["sty_count"]))

    console.print(table)


@template.command("delete")
@click.argument("template_id")
def template_delete(template_id):
    """Delete a template."""
    mgr = TemplateManager(settings.template_dir)
    mgr.delete(template_id)
    console.print(f"[green]Template {template_id} deleted.[/green]")


@cli.group()
def cache():
    """Manage extraction cache."""


@cache.command("list")
def cache_list():
    """List cached extractions."""
    async def _run():
        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as session:
            mgr = CacheManager(settings.cache_dir)
            entries = await mgr.list_entries(session)

        table = Table(title="Cache Entries")
        table.add_column("Hash", style="dim")
        table.add_column("PDF")
        table.add_column("Size")
        table.add_column("Last Accessed")

        for e in entries:
            table.add_row(
                e["hash"][:16] + "...",
                e["pdf_filename"],
                f"{e['size_bytes'] / 1e6:.1f}MB",
                e["last_accessed"] or "-",
            )

        console.print(table)
        console.print(f"\n{len(entries)} entries in cache.")

    asyncio.run(_run())


@cache.command("clear")
def cache_clear():
    """Clear all cached extractions."""
    async def _run():
        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as session:
            mgr = CacheManager(settings.cache_dir)
            await mgr.clear(session)
        console.print("[green]Cache cleared.[/green]")

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
