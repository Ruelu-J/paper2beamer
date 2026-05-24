"""SHA-256 hashing utilities for content-addressable caching."""

import hashlib
from pathlib import Path


def hash_pdf(file_path: str | Path) -> str:
    """Return SHA-256 hex digest of file contents."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Return SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()
