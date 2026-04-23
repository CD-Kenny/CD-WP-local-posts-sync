"""Small stdlib utility helpers for filesystem, JSON, and naming work."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sys
import unicodedata

from pathlib import Path
from urllib.parse import urlparse

PROFILE_FILE_NAME = "profile.json"
META_FILE_NAME = "meta.json"
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_asset_path(*parts: str) -> Path:
    return application_root().joinpath("assets", *parts)


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json_file(path: Path, default: object | None = None) -> object:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_file(path: Path, data: object) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False, ensure_ascii=True)
        handle.write("\n")


def normalize_site_url(value: str) -> str:
    cleaned = value.strip()
    return cleaned.rstrip("/")


def domain_from_site_url(value: str) -> str:
    parsed = urlparse(normalize_site_url(value))
    return parsed.netloc.lower()


def format_title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d+[\s._-]*", "", stem)
    stem = stem.replace("_", " ").replace("-", " ").replace(".", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or Path(filename).stem


def extract_menu_order(filename: str) -> int:
    match = re.match(r"^(\d+)[\s._-]*", Path(filename).stem)
    if not match:
        return 0
    return int(match.group(1))


def filename_without_order_prefix(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d+[\s._-]*", "", stem)
    return stem or Path(filename).stem


def has_menu_order_prefix(filename: str) -> bool:
    return re.match(r"^\d+[\s._-]+", Path(filename).stem) is not None


def build_numbered_filename(filename: str, menu_order: int, width: int = 0) -> str:
    prefix_width = max(width, len(str(menu_order)))
    prefix = str(menu_order).zfill(prefix_width) if prefix_width > 1 else str(menu_order)
    stem_without_prefix = filename_without_order_prefix(filename)
    return f"{prefix}-{stem_without_prefix}{Path(filename).suffix.lower()}"


def category_from_relative_path(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) <= 1:
        return ""
    return parts[0].replace("_", " ").replace("-", " ")


def relative_directory_key(relative_path: str) -> str:
    parent = Path(relative_path).parent
    if str(parent) == ".":
        return ""
    return parent.as_posix()


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_sync_checksum(
    file_checksum: str,
    title: str,
    category: str,
    content: str,
    excerpt: str,
    slug: str,
    status: str,
    menu_order: int,
    meta: dict[str, object],
) -> str:
    payload = {
        "file_checksum": file_checksum,
        "title": title,
        "category": category,
        "content": content,
        "excerpt": excerpt,
        "slug": slug,
        "status": status,
        "menu_order": menu_order,
        "meta": meta,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def guess_mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def guess_extension_from_url(url: str, mime_type: str = "") -> str:
    parsed = Path(urlparse(url).path)
    if parsed.suffix:
        return parsed.suffix.lower()
    guessed = mimetypes.guess_extension(mime_type or "")
    return guessed or ".jpg"


def safe_relative_key(path: Path) -> str:
    return path.as_posix()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower().strip()
    ascii_value = re.sub(r"[^a-z0-9\s-]", "", ascii_value)
    ascii_value = re.sub(r"[\s_-]+", "-", ascii_value)
    return ascii_value.strip("-")


def sanitize_path_segment(value: str, fallback: str = "item") -> str:
    cleaned = value.strip().replace("/", " ").replace("\\", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .")
    return cleaned or fallback