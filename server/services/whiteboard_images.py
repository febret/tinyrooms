"""Content-addressed storage for image-backed whiteboard PNGs."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
from pathlib import Path


WHITEBOARD_IMAGE_WIDTH = 1024
WHITEBOARD_IMAGE_HEIGHT = 640
WHITEBOARD_IMAGE_ASSET_PREFIX = "/assets/whiteboards"
WHITEBOARD_IMAGE_DATA_URL_PREFIX = "data:image/png;base64,"
WHITEBOARD_IMAGE_MAX_BYTES = 2 * 1024 * 1024

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_IMAGE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def image_digest(png_bytes: bytes) -> str:
    """Return the SHA-256 identity for canonical whiteboard PNG bytes."""

    return hashlib.sha256(png_bytes).hexdigest()


def image_url_for(digest: str) -> str:
    """Return the public asset URL for a validated image digest."""

    if not _IMAGE_HASH_PATTERN.match(digest):
        raise ValueError("Unknown whiteboard image.")
    return f"{WHITEBOARD_IMAGE_ASSET_PREFIX}/{digest}.png"


def digest_from_image_url(image_url: object) -> str:
    """Return the digest encoded in a whiteboard image URL."""

    if not isinstance(image_url, str):
        raise ValueError("A whiteboard image must be a URL.")
    prefix = f"{WHITEBOARD_IMAGE_ASSET_PREFIX}/"
    if not image_url.startswith(prefix) or not image_url.endswith(".png"):
        raise ValueError("A whiteboard image must use a whiteboard asset URL.")
    digest = image_url[len(prefix):-len(".png")]
    if not _IMAGE_HASH_PATTERN.match(digest):
        raise ValueError("A whiteboard image URL is invalid.")
    return digest


def decode_whiteboard_image(image: object) -> bytes:
    """Validate an uploaded PNG data URL and return canonical PNG bytes."""

    if not isinstance(image, str) or not image.startswith(WHITEBOARD_IMAGE_DATA_URL_PREFIX):
        raise ValueError("A whiteboard image must be a PNG data URL.")
    encoded = image[len(WHITEBOARD_IMAGE_DATA_URL_PREFIX):].strip()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("That whiteboard image could not be read.") from exc
    if not raw:
        raise ValueError("That whiteboard image was empty.")
    if len(raw) > WHITEBOARD_IMAGE_MAX_BYTES:
        raise ValueError("That whiteboard image is too large.")
    if not raw.startswith(_PNG_MAGIC):
        raise ValueError("That whiteboard image must be a PNG.")

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - Pillow is a required dependency
        raise ValueError("Server image support is unavailable.") from exc

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.size != (WHITEBOARD_IMAGE_WIDTH, WHITEBOARD_IMAGE_HEIGHT):
                raise ValueError("That whiteboard image must be 1024 by 640 pixels.")
            normalized = source.convert("RGB")
            buffer = io.BytesIO()
            normalized.save(buffer, format="PNG")
            canonical = buffer.getvalue()
    except UnidentifiedImageError as exc:
        raise ValueError("That whiteboard image could not be read.") from exc
    except OSError as exc:
        raise ValueError("That whiteboard image could not be read.") from exc
    if len(canonical) > WHITEBOARD_IMAGE_MAX_BYTES:
        raise ValueError("That whiteboard image is too large.")
    return canonical


class WhiteboardImageStore:
    """Persist canonical whiteboard PNGs under content-addressed filenames."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, digest: str) -> Path:
        """Return the filesystem path backing an image digest."""

        if not _IMAGE_HASH_PATTERN.match(digest):
            raise ValueError("Unknown whiteboard image.")
        return self._directory / f"{digest}.png"

    def exists(self, digest: str) -> bool:
        """Return whether *digest* already has persisted PNG bytes."""

        return self.path_for(digest).is_file()

    def store_data_url(self, image: object) -> dict[str, str]:
        """Store an uploaded data URL and return its canonical URL identity."""

        png_bytes = decode_whiteboard_image(image)
        digest = image_digest(png_bytes)
        target = self.path_for(digest)
        if not target.is_file():
            temporary = self._directory / f".{digest}.png.tmp"
            temporary.write_bytes(png_bytes)
            temporary.replace(target)
        return {"image_url": image_url_for(digest), "image_hash": digest}
