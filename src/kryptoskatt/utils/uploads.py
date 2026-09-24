"""Bounded reading of uploaded files (prevents memory exhaustion)."""

from fastapi import HTTPException, UploadFile

# Exchange CSV exports for private individuals are far below this.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_CHUNK = 1024 * 1024


async def read_upload(file: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read an upload, refusing anything larger than ``max_bytes`` (HTTP 413)."""
    parts: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)",
            )
        parts.append(chunk)
    return b"".join(parts)
