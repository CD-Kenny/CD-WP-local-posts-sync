from __future__ import annotations

from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_msi import MSI_PLATFORM

from build_tools.branding import (
    APP_COMMENTS,
    APP_COPYRIGHT,
    APP_DESCRIPTION,
    APP_DISPLAY_NAME,
    APP_KEYWORDS,
    APP_PUBLISHER,
    APP_SHORTCUT_NAME,
    APP_TRADEMARKS,
    GENERATED_ICON_PATH,
    PROGRAM_MENU_DIRECTORY_ID,
    PROGRAM_MENU_DIRECTORY_ROWS,
    ensure_branding_assets,
)
from wp_sync_app import __version__

ROOT = Path(__file__).resolve().parent
ensure_branding_assets(ROOT)

build_exe_options = {
    "packages": ["encodings", "tkinter", "wp_sync_app"],
    "includes": ["tkinter"],
    "excludes": ["unittest", "test", "doctest", "pydoc", "email.test"],
    "include_files": [
        (str(ROOT / "README.md"), "README.md"),
        (str(ROOT / "profile.example.json"), "profile.example.json"),
        (str(ROOT / "assets"), "assets"),
    ],
    "include_msvcr": True,
    "optimize": 1,
}

bdist_msi_options = {
    "add_to_path": False,
    "all_users": False,
    "initial_target_dir": r"[LocalAppDataFolder]Programs\WordPress Post Uploader",
    "directories": PROGRAM_MENU_DIRECTORY_ROWS,
    "install_icon": str(ROOT / GENERATED_ICON_PATH),
    "launch_on_finish": True,
    "output_name": f"CasualDevelopment-WordPressPostUploader-{__version__}-{MSI_PLATFORM}.msi",
    "product_name": APP_DISPLAY_NAME,
    "product_version": __version__,
    "summary_data": {
        "author": APP_PUBLISHER,
        "comments": APP_COMMENTS,
        "keywords": ", ".join(APP_KEYWORDS),
    },
    "upgrade_code": "{2A2CB88A-01E4-4E38-8D10-BC7E0C6E0C41}",
}

executables = [
    Executable(
        script=str(ROOT / "main.py"),
        base="gui",
        target_name="WordPressPostUploader.exe",
        icon=str(ROOT / GENERATED_ICON_PATH),
        shortcut_name=APP_SHORTCUT_NAME,
        shortcut_dir=PROGRAM_MENU_DIRECTORY_ID,
        copyright=APP_COPYRIGHT,
        trademarks=APP_TRADEMARKS,
    )
]

setup(
    name="WordPressPostUploader",
    version=__version__,
    author=APP_PUBLISHER,
    description=APP_DESCRIPTION,
    keywords=APP_KEYWORDS,
    long_description=APP_COMMENTS,
    options={
        "build_exe": build_exe_options,
        "bdist_msi": bdist_msi_options,
    },
    executables=executables,
)