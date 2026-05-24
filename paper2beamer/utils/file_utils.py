"""File and directory utilities."""

import shutil
import tempfile
import zipfile
from pathlib import Path


def make_temp_dir(prefix: str = "paper2beamer_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def cleanup_temp_dir(path: Path):
    shutil.rmtree(path, ignore_errors=True)


def create_zip(
    output_path: str | Path,
    files: dict[str, str | bytes],
) -> Path:
    output_path = Path(output_path)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            if isinstance(content, str):
                zf.writestr(arcname, content)
            else:
                zf.writestr(arcname, content)
    return output_path


def collect_directory_files(directory: str | Path,
                            prefix: str = "") -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    dir_path = Path(directory)
    if not dir_path.exists():
        return result
    for f in dir_path.iterdir():
        if f.is_file():
            arcname = f"{prefix}{f.name}" if prefix else f.name
            result[arcname] = f.read_bytes()
    return result
