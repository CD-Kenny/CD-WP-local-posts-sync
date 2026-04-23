"""Shared data models used by the desktop application."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class FolderReference:
    path: str
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "FolderReference":
        source = data or {}
        return cls(path=str(source.get("path", "")).strip(), enabled=bool(source.get("enabled", True)))

    def to_dict(self) -> dict:
        return {"path": self.path, "enabled": self.enabled}


@dataclass(slots=True)
class PostRecord:
    record_id: str = field(default_factory=lambda: uuid4().hex)
    title: str = ""
    content: str = ""
    excerpt: str = ""
    slug: str = ""
    status: str = ""
    category: str = ""
    menu_order: int = 0
    wordpress_id: int | None = None
    attachment_id: int | None = None
    file_checksum: str = ""
    checksum: str = ""
    source_key: str = ""
    remote_modified_gmt: str = ""
    featured_image_url: str = ""
    mime_type: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PostRecord":
        source = data or {}
        wordpress_id = source.get("wordpress_id")
        attachment_id = source.get("attachment_id")
        return cls(
            record_id=str(source.get("record_id") or uuid4().hex),
            title=str(source.get("title", "")),
            content=str(source.get("content", "")),
            excerpt=str(source.get("excerpt", "")),
            slug=str(source.get("slug", "")),
            status=str(source.get("status", "")),
            category=str(source.get("category", "")),
            menu_order=int(source.get("menu_order") or 0),
            wordpress_id=int(wordpress_id) if wordpress_id not in (None, "") else None,
            attachment_id=int(attachment_id) if attachment_id not in (None, "") else None,
            file_checksum=str(source.get("file_checksum", "")),
            checksum=str(source.get("checksum", "")),
            source_key=str(source.get("source_key", "")),
            remote_modified_gmt=str(source.get("remote_modified_gmt", "")),
            featured_image_url=str(source.get("featured_image_url", "")),
            mime_type=str(source.get("mime_type", "")),
            meta=dict(source.get("meta") or {}),
        )

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "title": self.title,
            "content": self.content,
            "excerpt": self.excerpt,
            "slug": self.slug,
            "status": self.status,
            "category": self.category,
            "menu_order": self.menu_order,
            "wordpress_id": self.wordpress_id,
            "attachment_id": self.attachment_id,
            "file_checksum": self.file_checksum,
            "checksum": self.checksum,
            "source_key": self.source_key,
            "remote_modified_gmt": self.remote_modified_gmt,
            "featured_image_url": self.featured_image_url,
            "mime_type": self.mime_type,
            "meta": self.meta,
        }


@dataclass(slots=True)
class FolderMeta:
    folder_name: str = ""
    folder_key: str = ""
    post_type: str = "post"
    taxonomy: str = "category"
    default_status: str = "draft"
    enable_order: bool = True
    default_content: str = ""
    default_excerpt: str = ""
    default_meta: dict[str, object] = field(default_factory=dict)
    posts: dict[str, PostRecord] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "FolderMeta":
        source = data or {}
        raw_posts = dict(source.get("posts") or {})
        return cls(
            folder_name=str(source.get("folder_name", "")),
            folder_key=str(source.get("folder_key", "")),
            post_type=str(source.get("post_type", "post")),
            taxonomy=str(source.get("taxonomy", "category")),
            default_status=str(source.get("default_status", "draft")),
            enable_order=bool(source.get("enable_order", True)),
            default_content=str(source.get("default_content", "")),
            default_excerpt=str(source.get("default_excerpt", "")),
            default_meta=dict(source.get("default_meta") or {}),
            posts={key.replace('\\', '/'): PostRecord.from_dict(value) for key, value in raw_posts.items()},
        )

    def to_dict(self) -> dict:
        return {
            "folder_name": self.folder_name,
            "folder_key": self.folder_key,
            "post_type": self.post_type,
            "taxonomy": self.taxonomy,
            "default_status": self.default_status,
            "enable_order": self.enable_order,
            "default_content": self.default_content,
            "default_excerpt": self.default_excerpt,
            "default_meta": self.default_meta,
            "posts": {key: value.to_dict() for key, value in sorted(self.posts.items())},
        }


@dataclass(slots=True)
class SiteProfile:
    domain: str
    site_url: str = ""
    username: str = ""
    password: str = ""
    folders: list[FolderReference] = field(default_factory=list)

    @classmethod
    def from_dict(cls, domain: str, data: dict | None) -> "SiteProfile":
        source = data or {}
        raw_folders = source.get("folders") or []
        return cls(
            domain=domain,
            site_url=str(source.get("site_url", "")),
            username=str(source.get("username", "")),
            password=str(source.get("password", "")),
            folders=[FolderReference.from_dict(item) for item in raw_folders],
        )

    def to_dict(self) -> dict:
        return {
            "site_url": self.site_url,
            "username": self.username,
            "password": self.password,
            "folders": [folder.to_dict() for folder in self.folders],
        }


@dataclass(slots=True)
class AppProfiles:
    active_domain: str = ""
    profiles: dict[str, SiteProfile] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "AppProfiles":
        source = data or {}
        raw_profiles = dict(source.get("profiles") or {})
        profiles = {domain: SiteProfile.from_dict(domain, value) for domain, value in raw_profiles.items()}
        active_domain = str(source.get("active_domain", ""))
        if active_domain and active_domain not in profiles:
            active_domain = ""
        return cls(active_domain=active_domain, profiles=profiles)

    def to_dict(self) -> dict:
        return {
            "active_domain": self.active_domain,
            "profiles": {domain: profile.to_dict() for domain, profile in sorted(self.profiles.items())},
        }


@dataclass(slots=True)
class LocalPost:
    absolute_path: str
    relative_path: str
    stored_relative_path: str | None
    title: str
    category: str
    mime_type: str
    file_checksum: str
    menu_order: int
    sync_checksum: str
    record: PostRecord


@dataclass(slots=True)
class SyncAction:
    action: str
    folder_path: str
    relative_path: str
    title: str
    message: str = ""
    wordpress_id: int | None = None