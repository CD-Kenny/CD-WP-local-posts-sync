"""Generate Windows branding assets from the Casual Development SVG logo."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess

from dataclasses import dataclass
from pathlib import Path

APP_PUBLISHER = "Casual Development"
APP_DISPLAY_NAME = "Casual Development WordPress Post Uploader"
APP_SHORTCUT_NAME = "WordPress Post Uploader"
APP_DESCRIPTION = "Casual Development desktop uploader and sync tool for WordPress posts and custom post types."
APP_COMMENTS = "Casual Development desktop tool for uploading, downloading, and syncing local folders with WordPress posts and custom post types."
APP_COPYRIGHT = "Copyright (c) 2026 Casual Development"
APP_TRADEMARKS = "Casual Development"
APP_KEYWORDS = ["casual development", "wordpress", "desktop sync", "uploader", "tkinter"]

PROGRAM_MENU_ROOT_ID = "ProgramMenuFolder"
PROGRAM_MENU_DIRECTORY_ID = "CasualDevelopmentMenu"
PROGRAM_MENU_ROOT_ROW = (
    PROGRAM_MENU_ROOT_ID,
    "TARGETDIR",
    ".",
)
PROGRAM_MENU_DIRECTORY_ROW = (
    PROGRAM_MENU_DIRECTORY_ID,
    PROGRAM_MENU_ROOT_ID,
    "CASUAL~1|Casual Development",
)
PROGRAM_MENU_DIRECTORY_ROWS = [PROGRAM_MENU_ROOT_ROW, PROGRAM_MENU_DIRECTORY_ROW]

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
GENERATED_DIR = Path("assets") / "generated"
SVG_LOGO_PATH = Path("assets") / "logo.svg"
GENERATED_ICON_PATH = GENERATED_DIR / "logo.ico"
GENERATED_PNG_64_PATH = GENERATED_DIR / "logo-64.png"
GENERATED_PNG_256_PATH = GENERATED_DIR / "logo-256.png"


@dataclass(slots=True)
class BrandingAssets:
    icon_path: Path
    logo_png_path: Path


def repo_root(root: Path | None = None) -> Path:
    return root or Path(__file__).resolve().parent.parent


def ensure_branding_assets(root: Path | None = None, force: bool = False) -> BrandingAssets:
    root_path = repo_root(root)
    svg_path = root_path / SVG_LOGO_PATH
    generated_dir = root_path / GENERATED_DIR
    generated_dir.mkdir(parents=True, exist_ok=True)

    icon_path = root_path / GENERATED_ICON_PATH
    png_64_path = root_path / GENERATED_PNG_64_PATH

    if not force and icon_path.exists() and png_64_path.exists() and icon_path.stat().st_mtime >= svg_path.stat().st_mtime:
        return BrandingAssets(icon_path=icon_path, logo_png_path=png_64_path)

    inkscape_path = find_inkscape()
    if inkscape_path is None:
        if icon_path.exists() and png_64_path.exists():
            return BrandingAssets(icon_path=icon_path, logo_png_path=png_64_path)
        raise RuntimeError(
            "Inkscape is required to generate Windows branding assets from assets/logo.svg. "
            "Install Inkscape or set INKSCAPE_EXE to its full path."
        )

    png_paths: list[Path] = []
    for size in ICON_SIZES:
        png_path = generated_dir / f"logo-{size}.png"
        export_png(inkscape_path, svg_path, png_path, size)
        png_paths.append(png_path)

    build_ico(icon_path, png_paths)
    return BrandingAssets(icon_path=icon_path, logo_png_path=png_64_path)


def stamp_executable_metadata(executable_path: Path, root: Path | None = None) -> None:
    from cx_Freeze.winversioninfo import VersionInfo

    version = read_app_version(root)
    version_info = VersionInfo(
        version,
        comments=APP_COMMENTS,
        description=APP_DESCRIPTION,
        company=APP_PUBLISHER,
        product=APP_DISPLAY_NAME,
        copyright=APP_COPYRIGHT,
        trademarks=APP_TRADEMARKS,
        verbose=False,
    )
    version_info.stamp(executable_path)


def find_inkscape() -> str | None:
    candidates = []

    for item in (
        Path((Path.home() / "AppData" / "Local" / "Programs" / "Inkscape" / "bin" / "inkscape.exe")),
        Path((Path("C:/Program Files/Inkscape/bin/inkscape.exe"))),
        Path((Path("C:/Program Files (x86)/Inkscape/bin/inkscape.exe"))),
    ):
        candidates.append(item)

    configured = None
    value = os.environ.get("INKSCAPE_EXE", "").strip()
    if value:
        configured = Path(value)
    if configured is not None:
        candidates.insert(0, configured)

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    resolved = shutil.which("inkscape.exe") or shutil.which("inkscape")
    return resolved


def export_png(inkscape_path: str, svg_path: Path, png_path: Path, size: int) -> None:
    command = [
        inkscape_path,
        str(svg_path),
        f"--export-filename={png_path}",
        "--export-type=png",
        f"--export-width={size}",
        f"--export-height={size}",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "Inkscape failed without output."
        raise RuntimeError(f"Could not export {png_path.name} from {svg_path.name}: {stderr}")


def build_ico(icon_path: Path, png_paths: list[Path]) -> None:
    images = [path.read_bytes() for path in png_paths]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries: list[bytes] = []
    offset = 6 + (16 * len(images))

    for png_path, image_data in zip(png_paths, images, strict=True):
        size = parse_size_from_name(png_path)
        width = 0 if size >= 256 else size
        height = 0 if size >= 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                width,
                height,
                0,
                0,
                1,
                32,
                len(image_data),
                offset,
            )
        )
        offset += len(image_data)

    with icon_path.open("wb") as handle:
        handle.write(header)
        for entry in entries:
            handle.write(entry)
        for image_data in images:
            handle.write(image_data)


def parse_size_from_name(path: Path) -> int:
    suffix = path.stem.rsplit("-", maxsplit=1)[-1]
    return int(suffix)


def read_app_version(root: Path | None = None) -> str:
    root_path = repo_root(root)
    version_file = root_path / "wp_sync_app" / "__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', version_file.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not determine app version from {version_file}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Regenerate branding assets even if cached files are newer than the source SVG.")
    parser.add_argument("--stamp-exe", type=Path, help="Path to a frozen Windows executable that should receive the branded version resource.")
    args = parser.parse_args()

    assets = ensure_branding_assets(force=args.force)
    if args.stamp_exe:
        stamp_executable_metadata(args.stamp_exe)
    print(f"Branding icon: {assets.icon_path}")
    print(f"Branding PNG: {assets.logo_png_path}")
    if args.stamp_exe:
        print(f"Stamped executable metadata: {args.stamp_exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())