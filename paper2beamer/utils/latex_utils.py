"""LaTeX helper utilities."""

import re


def escape_latex(text: str) -> str:
    escapes = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    result = text
    for char, repl in escapes:
        result = result.replace(char, repl)
    return result


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip()


def is_latex_installed() -> bool:
    import shutil
    return shutil.which("latexmk") is not None


def count_effective_lines(latex_content: str) -> int:
    lines = latex_content.count("\n") + 1
    for match in re.finditer(r'\$.*?\$', latex_content):
        lines += match.group(0).count("\n")
    return max(1, lines)
