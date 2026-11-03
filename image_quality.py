#!/usr/bin/env python3
"""Strict source-image validation for SolePick recipe publishing."""
import io
import statistics
import urllib.request
from PIL import Image, ImageFilter, ImageStat

MIN_WIDTH = 1200
MIN_HEIGHT = 800
MIN_EDGE_VARIANCE = 18.0
MAX_BYTES = 18 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def inspect_image_url(url):
    """Download and decode a source image; return dimensions and a conservative sharpness signal."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return {"ok": False, "reason": "image URL must use HTTPS"}
    request = urllib.request.Request(url, headers={"User-Agent": "SolePickRecipesBot/1.2 (+https://solepick.site)"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            data = response.read(MAX_BYTES + 1)
    except Exception as exc:
        return {"ok": False, "reason": "image download failed: " + type(exc).__name__}
    if len(data) > MAX_BYTES:
        return {"ok": False, "reason": "image exceeds 18 MB"}
    if not content_type.startswith("image/"):
        return {"ok": False, "reason": "response is not an image"}
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            width, height = source.size
            image_format = source.format
            if image_format not in ALLOWED_FORMATS:
                return {"ok": False, "reason": "unsupported image format", "width": width, "height": height}
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return {"ok": False, "reason": "source image below 1200x800", "width": width, "height": height}
            ratio = width / height
            if ratio < 1.2 or ratio > 2.4:
                return {"ok": False, "reason": "unsuitable food-photo aspect ratio", "width": width, "height": height}
            preview = source.convert("L")
            preview.thumbnail((512, 512))
            edges = preview.filter(ImageFilter.FIND_EDGES)
            edge_variance = ImageStat.Stat(edges).var[0]
            if edge_variance < MIN_EDGE_VARIANCE:
                return {"ok": False, "reason": "image appears unusually soft or blurry", "width": width, "height": height, "edge_variance": round(edge_variance, 2)}
            return {"ok": True, "width": width, "height": height, "format": image_format,
                    "bytes": len(data), "edge_variance": round(edge_variance, 2)}
    except Exception as exc:
        return {"ok": False, "reason": "image decode failed: " + type(exc).__name__}


def is_high_quality_image(result):
    return bool(result and result.get("ok") is True
                and result.get("width", 0) >= MIN_WIDTH
                and result.get("height", 0) >= MIN_HEIGHT
                and result.get("edge_variance", 0) >= MIN_EDGE_VARIANCE)
