"""Beamer template ZIP validation and management."""

import shutil
import uuid
import zipfile
from pathlib import Path

VALID_EXTENSIONS = {
    ".sty", ".cls", ".cfg", ".def", ".fd",
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg",
    ".ttf", ".otf", ".vf", ".tfm",
    ".bib", ".bst",
    ".tex", ".dtx", ".ins",
    ".md", ".txt", ".markdown", ".rst",
    ".log", ".aux", ".toc", ".out",
}
MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_FILES = 50


class TemplateValidationError(Exception):
    pass


class TemplateManager:
    def __init__(self, template_dir: str | Path):
        self.template_dir = Path(template_dir)
        self.template_dir.mkdir(parents=True, exist_ok=True)

    def validate_zip(self, zip_path: str | Path) -> tuple[bool, str]:
        zip_path = Path(zip_path)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                if len(names) > MAX_ZIP_FILES:
                    return False, (
                        f"ZIP contains {len(names)} files, "
                        f"maximum is {MAX_ZIP_FILES}"
                    )

                has_sty = False
                for name in names:
                    if ".." in name or name.startswith("/"):
                        return False, f"Invalid path in ZIP: {name}"
                    if name.endswith("/"):
                        continue
                    ext = Path(name).suffix.lower()
                    if ext not in VALID_EXTENSIONS:
                        return False, (
                            f"File type '{ext}' not allowed: {name}"
                        )
                    if ext == ".sty" and "beamertheme" in name.lower():
                        has_sty = True
                    elif ext == ".sty":
                        has_sty = True

                if not has_sty:
                    return False, (
                        "ZIP must contain at least one .sty file "
                        "(preferably beamertheme*.sty)"
                    )

                total_size = sum(
                    info.file_size for info in zf.infolist()
                )
                if total_size > MAX_ZIP_SIZE:
                    return False, (
                        f"Total extracted size {total_size / 1e6:.1f}MB "
                        f"exceeds maximum {MAX_ZIP_SIZE / 1e6:.0f}MB"
                    )

                return True, "Template ZIP is valid."

        except zipfile.BadZipFile:
            return False, "File is not a valid ZIP archive."
        except Exception as e:
            return False, f"Validation error: {e}"

    def install(self, zip_path: str | Path, name: str,
                description: str = "") -> str:
        valid, msg = self.validate_zip(zip_path)
        if not valid:
            raise TemplateValidationError(msg)

        template_id = str(uuid.uuid4())
        dest_dir = self.template_dir / template_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Find the common prefix directory in the ZIP
            names = [n for n in zf.namelist() if not n.endswith("/")]
            common_prefix = ""
            if names:
                parts = Path(names[0]).parts
                if len(parts) > 1:
                    common_prefix = parts[0] + "/"
            for member in zf.infolist():
                if member.filename.endswith("/"):
                    continue
                # Strip the common prefix dir, preserve subdirs
                rel_path = member.filename
                if common_prefix and rel_path.startswith(common_prefix):
                    rel_path = rel_path[len(common_prefix):]
                target = dest_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

        return template_id

    def get_template_dir(self, template_id: str) -> str:
        return str(self.template_dir / template_id)

    def delete(self, template_id: str):
        template_dir = self.template_dir / template_id
        if template_dir.exists():
            shutil.rmtree(template_dir)

    def list_local(self) -> list[dict]:
        result: list[dict] = []
        for d in self.template_dir.iterdir():
            if d.is_dir():
                sty_files = list(d.glob("*.sty"))
                result.append({
                    "id": d.name,
                    "sty_count": len(sty_files),
                    "path": str(d),
                })
        return result
