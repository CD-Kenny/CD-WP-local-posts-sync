"""Configuration stores for profile.json and folder-level meta.json files."""

from __future__ import annotations

import json
import os
import shutil
import sys

from pathlib import Path

from .models import AppProfiles, FolderMeta
from .utils import META_FILE_NAME, PROFILE_FILE_NAME, ensure_directory, read_json_file, slugify, write_json_file

APP_DATA_DIRECTORY_NAME = "WordPressPostUploader"


class ConfigError(RuntimeError):
    """Raised when a local configuration file cannot be read or written."""


def program_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def profile_root() -> Path:
    override = os.environ.get("WP_SYNC_PROFILE_ROOT", "").strip()
    if override:
        return Path(override).expanduser()

    if not is_frozen_app():
        return program_root()

    appdata_base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if appdata_base:
        return Path(appdata_base) / APP_DATA_DIRECTORY_NAME
    return Path.home() / f".{APP_DATA_DIRECTORY_NAME}"


class ProfileStore:
    """Load and save profile.json in the active profile storage directory."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or profile_root()
        self.path = self.root / PROFILE_FILE_NAME

    def load(self) -> AppProfiles:
        try:
            self._migrate_legacy_profile_if_needed()
            if not self.path.exists():
                profiles = AppProfiles()
                self.save(profiles)
                return profiles
            raw = read_json_file(self.path, {"active_domain": "", "profiles": {}})
            if not isinstance(raw, dict):
                raise ConfigError(f"{self.path} must contain a JSON object.")
            return AppProfiles.from_dict(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Could not parse {self.path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read {self.path}: {exc}") from exc

    def save(self, profiles: AppProfiles) -> None:
        try:
            write_json_file(self.path, profiles.to_dict())
        except OSError as exc:
            raise ConfigError(f"Could not write {self.path}: {exc}") from exc

    def _migrate_legacy_profile_if_needed(self) -> None:
        legacy_path = program_root() / PROFILE_FILE_NAME
        if self.path == legacy_path or self.path.exists() or not legacy_path.exists():
            return

        try:
            ensure_directory(self.root)
            shutil.copy2(legacy_path, self.path)
        except OSError as exc:
            raise ConfigError(
                f"Could not migrate existing profile.json from {legacy_path} to {self.path}: {exc}"
            ) from exc


class FolderMetaStore:
    """Load and save meta.json inside sync folders."""

    def load(self, folder_path: Path) -> FolderMeta:
        if not folder_path.exists():
            raise ConfigError(f"Folder does not exist: {folder_path}")
        if not folder_path.is_dir():
            raise ConfigError(f"Folder path is not a directory: {folder_path}")

        meta_path = folder_path / META_FILE_NAME
        if not meta_path.exists():
            meta = FolderMeta(folder_name=folder_path.name, folder_key=slugify(folder_path.name) or "posts")
            self.save(folder_path, meta)
            return meta

        try:
            raw = read_json_file(meta_path, {})
            if not isinstance(raw, dict):
                raise ConfigError(f"{meta_path} must contain a JSON object.")
            meta = FolderMeta.from_dict(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Could not parse {meta_path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"Could not read {meta_path}: {exc}") from exc

        if not meta.folder_name:
            meta.folder_name = folder_path.name
        if not meta.folder_key:
            meta.folder_key = slugify(meta.folder_name) or "posts"
        return meta

    def save(self, folder_path: Path, meta: FolderMeta) -> None:
        meta_path = folder_path / META_FILE_NAME
        meta.folder_name = meta.folder_name or folder_path.name
        meta.folder_key = meta.folder_key or slugify(meta.folder_name) or "posts"
        try:
            write_json_file(meta_path, meta.to_dict())
        except OSError as exc:
            raise ConfigError(f"Could not write {meta_path}: {exc}") from exc