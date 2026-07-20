from __future__ import annotations

import io
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import Settings
from ..constants import new_id
from ..models import StyleReference

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


async def normalize_style_reference(file: UploadFile, settings: Settings) -> StyleReference:
    mime = (file.content_type or "").lower()
    if mime not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Use a PNG, JPEG, or WebP image")
    data = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Style-reference image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Style-reference image must be 10 MB or smaller"
        )

    reference_id = new_id()
    destination = settings.style_reference_dir / f"{reference_id}.png"
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Style-reference image exceeds the {MAX_IMAGE_PIXELS:,}-pixel limit"
                )
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            image.save(destination, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not read style reference: {exc}"
        ) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    with Image.open(destination) as stored:
        width, height = stored.size
    return StyleReference(
        id=reference_id,
        path=str(destination),
        width=width,
        height=height,
        size_bytes=destination.stat().st_size,
        original_name=Path(file.filename or "").name[:255],
    )
