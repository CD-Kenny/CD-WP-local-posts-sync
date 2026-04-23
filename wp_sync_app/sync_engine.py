"""Folder scanning, plan generation, and upload or download execution."""

from __future__ import annotations

import base64

from pathlib import Path

from .config import FolderMetaStore
from .models import FolderMeta, LocalPost, PostRecord, SyncAction
from .utils import (
    SUPPORTED_IMAGE_EXTENSIONS,
    build_numbered_filename,
    extract_menu_order,
    filename_without_order_prefix,
    has_menu_order_prefix,
    category_from_relative_path,
    compute_sync_checksum,
    ensure_directory,
    format_title_from_filename,
    guess_extension_from_url,
    guess_mime_type,
    relative_directory_key,
    safe_relative_key,
    sanitize_path_segment,
    sha256_for_file,
    slugify,
)
from .wordpress import WordPressClient


class FolderSyncService:
    """Perform preview, sync, and download operations for one configured folder."""

    def __init__(self, meta_store: FolderMetaStore | None = None) -> None:
        self.meta_store = meta_store or FolderMetaStore()

    def preview_sync(self, folder_path: Path, meta: FolderMeta) -> list[SyncAction]:
        local_posts = self.scan_local_posts(folder_path, meta)
        results: list[SyncAction] = []
        matched_paths = {local_post.stored_relative_path or relative_path for relative_path, local_post in local_posts.items()}

        for relative_path, local_post in local_posts.items():
            stored_path = local_post.stored_relative_path or relative_path
            stored = meta.posts.get(stored_path)
            action = self._determine_action(stored, local_post)
            results.append(
                SyncAction(
                    action=action,
                    folder_path=str(folder_path),
                    relative_path=relative_path,
                    title=local_post.title,
                    wordpress_id=stored.wordpress_id if stored else None,
                )
            )

        for relative_path in sorted(set(meta.posts) - matched_paths):
            stored = meta.posts[relative_path]
            action = "delete" if stored.wordpress_id else "prune"
            results.append(
                SyncAction(
                    action=action,
                    folder_path=str(folder_path),
                    relative_path=relative_path,
                    title=stored.title or relative_path,
                    message="Local file was removed.",
                    wordpress_id=stored.wordpress_id,
                )
            )

        return self._sort_actions(results)

    def sync_folder(self, folder_path: Path, meta: FolderMeta, client: WordPressClient) -> list[SyncAction]:
        local_posts = self.scan_local_posts(folder_path, meta)
        plan = self.preview_sync(folder_path, meta)
        results: list[SyncAction] = []
        pending_order_updates: list[tuple[SyncAction, LocalPost]] = []

        for action in plan:
            try:
                if action.action == "unchanged":
                    results.append(action)
                    continue

                if action.action == "reorder":
                    pending_order_updates.append((action, local_posts[action.relative_path]))
                    continue

                if action.action in {"create", "update"}:
                    local_post = local_posts[action.relative_path]
                    response = client.sync_post(self._build_sync_payload(meta, local_post))
                    updated_record = local_post.record
                    previous_relative_path = local_post.stored_relative_path
                    updated_record.title = local_post.title
                    updated_record.category = local_post.category
                    updated_record.menu_order = local_post.menu_order
                    updated_record.file_checksum = local_post.file_checksum
                    updated_record.checksum = local_post.sync_checksum
                    updated_record.wordpress_id = self._coerce_int(response.get("id"))
                    updated_record.attachment_id = self._coerce_int(response.get("attachment_id"))
                    updated_record.remote_modified_gmt = str(response.get("modified_gmt", ""))
                    updated_record.featured_image_url = str(response.get("featured_image_url", ""))
                    updated_record.source_key = str(response.get("source_key") or updated_record.source_key)
                    if previous_relative_path and previous_relative_path != action.relative_path:
                        meta.posts.pop(previous_relative_path, None)
                    meta.posts[action.relative_path] = updated_record
                    results.append(
                        SyncAction(
                            action=action.action,
                            folder_path=action.folder_path,
                            relative_path=action.relative_path,
                            title=local_post.title,
                            message=str(response.get("message", "Synchronized.")),
                            wordpress_id=updated_record.wordpress_id,
                        )
                    )
                    continue

                if action.action == "delete":
                    stored = meta.posts.get(action.relative_path)
                    if stored and stored.wordpress_id:
                        client.delete_post(stored.wordpress_id)
                    meta.posts.pop(action.relative_path, None)
                    results.append(
                        SyncAction(
                            action="delete",
                            folder_path=action.folder_path,
                            relative_path=action.relative_path,
                            title=action.title,
                            message="Deleted remote post because the local image was removed.",
                            wordpress_id=action.wordpress_id,
                        )
                    )
                    continue

                if action.action == "prune":
                    meta.posts.pop(action.relative_path, None)
                    results.append(
                        SyncAction(
                            action="prune",
                            folder_path=action.folder_path,
                            relative_path=action.relative_path,
                            title=action.title,
                            message="Removed stale metadata entry.",
                            wordpress_id=action.wordpress_id,
                        )
                    )
            except Exception as exc:
                results.append(
                    SyncAction(
                        action="error",
                        folder_path=action.folder_path,
                        relative_path=action.relative_path,
                        title=action.title,
                        message=str(exc),
                        wordpress_id=action.wordpress_id,
                    )
                )

        try:
            results.extend(self._apply_order_updates(str(folder_path), meta, client, pending_order_updates))
        except Exception as exc:
            for action, _local_post in pending_order_updates:
                results.append(
                    SyncAction(
                        action="error",
                        folder_path=action.folder_path,
                        relative_path=action.relative_path,
                        title=action.title,
                        message=str(exc),
                        wordpress_id=action.wordpress_id,
                    )
                )

        self.meta_store.save(folder_path, meta)
        return self._sort_actions(results)

    def download_folder(self, folder_path: Path, meta: FolderMeta, client: WordPressClient) -> list[SyncAction]:
        results: list[SyncAction] = []
        exported_posts = client.export_posts(meta.post_type, meta.taxonomy)

        for item in exported_posts:
            try:
                relative_path = self._resolve_download_relative_path(item)
                absolute_path = folder_path / Path(relative_path)
                ensure_directory(absolute_path.parent)

                featured_image_url = str(item.get("featured_image_url", ""))
                if featured_image_url:
                    image_bytes = client.download_binary(featured_image_url)
                    if absolute_path.exists() and absolute_path.read_bytes() != image_bytes:
                        results.append(
                            SyncAction(
                                action="conflict",
                                folder_path=str(folder_path),
                                relative_path=relative_path,
                                title=str(item.get("title", "")) or relative_path,
                                message="Skipped download because the local file has different contents.",
                                wordpress_id=self._coerce_int(item.get("id")),
                            )
                        )
                        continue
                    absolute_path.write_bytes(image_bytes)
                elif not absolute_path.exists():
                    results.append(
                        SyncAction(
                            action="error",
                            folder_path=str(folder_path),
                            relative_path=relative_path,
                            title=str(item.get("title", "")) or relative_path,
                            message="The exported post has no featured image, so no local file could be created.",
                            wordpress_id=self._coerce_int(item.get("id")),
                        )
                    )
                    continue

                category = self._category_from_export_item(item, relative_path)
                source_key = str(item.get("source_key", ""))
                record_id = self._record_id_from_source_key(meta, source_key)
                record = PostRecord(
                    record_id=record_id,
                    title=str(item.get("title", "")),
                    content=str(item.get("content", "")),
                    excerpt=str(item.get("excerpt", "")),
                    slug=str(item.get("slug", "")),
                    status=str(item.get("status", meta.default_status)),
                    category=category,
                    menu_order=self._coerce_int(item.get("menu_order")) or 0,
                    wordpress_id=self._coerce_int(item.get("id")),
                    attachment_id=self._coerce_int(item.get("attachment_id")),
                    file_checksum=sha256_for_file(absolute_path) if absolute_path.exists() else "",
                    checksum=str(item.get("sync_checksum", "")),
                    source_key=source_key or self.build_source_key(meta, record_id),
                    remote_modified_gmt=str(item.get("modified_gmt", "")),
                    featured_image_url=featured_image_url,
                    mime_type=str(item.get("attachment_mime_type") or guess_mime_type(absolute_path)),
                    meta=dict(item.get("meta") or {}),
                )
                meta.posts[relative_path] = record
                results.append(
                    SyncAction(
                        action="download",
                        folder_path=str(folder_path),
                        relative_path=relative_path,
                        title=record.title or relative_path,
                        message="Downloaded from WordPress.",
                        wordpress_id=record.wordpress_id,
                    )
                )
            except Exception as exc:
                title = str(item.get("title", "")) or "unknown"
                results.append(
                    SyncAction(
                        action="error",
                        folder_path=str(folder_path),
                        relative_path=str(item.get("source_path", "")),
                        title=title,
                        message=str(exc),
                        wordpress_id=self._coerce_int(item.get("id")),
                    )
                )

        self.meta_store.save(folder_path, meta)
        return self._sort_actions(results)

    def list_ordered_posts(self, folder_path: Path, meta: FolderMeta) -> dict[str, list[LocalPost]]:
        grouped: dict[str, list[LocalPost]] = {}
        for local_post in self.scan_local_posts(folder_path, meta).values():
            group = relative_directory_key(local_post.relative_path)
            grouped.setdefault(group, []).append(local_post)

        for items in grouped.values():
            items.sort(key=self._local_post_order_key)

        return dict(sorted(grouped.items(), key=lambda item: item[0].lower()))

    def number_unnumbered_files(self, folder_path: Path, meta: FolderMeta) -> list[SyncAction]:
        if not meta.enable_order:
            return []

        rename_plan: dict[str, str] = {}
        for group, items in self.list_ordered_posts(folder_path, meta).items():
            unnumbered = [item for item in items if not has_menu_order_prefix(Path(item.relative_path).name)]
            if not unnumbered:
                continue

            next_order = max((item.menu_order for item in items if has_menu_order_prefix(Path(item.relative_path).name)), default=0) + 1
            width = max(2, len(str(next_order + len(unnumbered) - 1)))
            for local_post in sorted(unnumbered, key=self._local_post_order_key):
                target_relative_path = self._build_order_target_relative_path(group, local_post.relative_path, next_order, width)
                if target_relative_path != local_post.relative_path:
                    rename_plan[local_post.relative_path] = target_relative_path
                next_order += 1

        actions = self._apply_rename_plan(
            folder_path,
            meta,
            rename_plan,
            action_name="reorder",
            message="Added missing number prefix.",
        )
        self.meta_store.save(folder_path, meta)
        return self._sort_actions(actions)

    def reorder_category_posts(
        self,
        folder_path: Path,
        meta: FolderMeta,
        order_group: str,
        ordered_relative_paths: list[str],
    ) -> list[SyncAction]:
        if not meta.enable_order:
            return []

        grouped = self.list_ordered_posts(folder_path, meta)
        current_paths = [item.relative_path for item in grouped.get(order_group, [])]
        if set(current_paths) != set(ordered_relative_paths):
            raise ValueError("The requested reorder set does not match the files in the selected category.")

        width = max(2, len(str(len(ordered_relative_paths))))
        rename_plan: dict[str, str] = {}
        for index, relative_path in enumerate(ordered_relative_paths, start=1):
            target_relative_path = self._build_order_target_relative_path(order_group, relative_path, index, width)
            if target_relative_path != relative_path:
                rename_plan[relative_path] = target_relative_path

        actions = self._apply_rename_plan(
            folder_path,
            meta,
            rename_plan,
            action_name="reorder",
            message="Updated local file order.",
        )
        self.meta_store.save(folder_path, meta)
        return self._sort_actions(actions)

    def save_order_changes(self, folder_path: Path, meta: FolderMeta, client: WordPressClient) -> list[SyncAction]:
        if not meta.enable_order:
            return []

        local_posts = self.scan_local_posts(folder_path, meta)
        pending_order_updates: list[tuple[SyncAction, LocalPost]] = []
        for relative_path, local_post in local_posts.items():
            stored = meta.posts.get(local_post.stored_relative_path or relative_path)
            if stored is None or not stored.wordpress_id:
                continue
            if self._determine_action(stored, local_post) != "reorder":
                continue
            pending_order_updates.append(
                (
                    SyncAction(
                        action="reorder",
                        folder_path=str(folder_path),
                        relative_path=relative_path,
                        title=local_post.title,
                        wordpress_id=stored.wordpress_id,
                    ),
                    local_post,
                )
            )

        results = self._apply_order_updates(str(folder_path), meta, client, pending_order_updates)
        self.meta_store.save(folder_path, meta)
        return self._sort_actions(results)

    def scan_local_posts(self, folder_path: Path, meta: FolderMeta) -> dict[str, LocalPost]:
        if not folder_path.exists():
            raise FileNotFoundError(f"Folder does not exist: {folder_path}")

        posts: dict[str, LocalPost] = {}
        stored_posts = dict(meta.posts)
        unmatched_stored_paths = set(stored_posts)
        for file_path in sorted(folder_path.rglob("*")):
            if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                continue

            relative_path = safe_relative_key(file_path.relative_to(folder_path))
            file_checksum = sha256_for_file(file_path)
            existing_path = relative_path if relative_path in stored_posts else self._match_renamed_record(
                stored_posts,
                unmatched_stored_paths,
                relative_path,
                file_checksum,
            )
            if existing_path is not None:
                unmatched_stored_paths.discard(existing_path)
            existing = stored_posts.get(existing_path or relative_path, PostRecord())
            title = existing.title.strip() or format_title_from_filename(file_path.name)
            category = existing.category.strip() or category_from_relative_path(relative_path)
            content = existing.content or meta.default_content
            excerpt = existing.excerpt or meta.default_excerpt
            status = existing.status or meta.default_status
            slug = existing.slug or slugify(title)
            menu_order = extract_menu_order(file_path.name) if meta.enable_order else 0
            record = PostRecord(
                record_id=existing.record_id,
                title=title,
                content=content,
                excerpt=excerpt,
                slug=slug,
                status=status,
                category=category,
                menu_order=menu_order,
                wordpress_id=existing.wordpress_id,
                attachment_id=existing.attachment_id,
                file_checksum=file_checksum,
                checksum=existing.checksum,
                source_key=existing.source_key or self.build_source_key(meta, existing.record_id),
                remote_modified_gmt=existing.remote_modified_gmt,
                featured_image_url=existing.featured_image_url,
                mime_type=guess_mime_type(file_path),
                meta={**meta.default_meta, **existing.meta},
            )
            sync_checksum = compute_sync_checksum(
                file_checksum=file_checksum,
                title=title,
                category=category,
                content=content,
                excerpt=excerpt,
                slug=slug,
                status=status,
                menu_order=menu_order,
                meta=record.meta,
            )
            posts[relative_path] = LocalPost(
                absolute_path=str(file_path),
                relative_path=relative_path,
                stored_relative_path=existing_path if existing_path != relative_path else None,
                title=title,
                category=category,
                mime_type=record.mime_type,
                file_checksum=file_checksum,
                menu_order=menu_order,
                sync_checksum=sync_checksum,
                record=record,
            )

        return posts

    def build_source_key(self, meta: FolderMeta, record_id: str) -> str:
        return f"{meta.folder_key}:{record_id}"

    def _record_id_from_source_key(self, meta: FolderMeta, source_key: str) -> str:
        prefix = f"{meta.folder_key}:"
        if source_key.startswith(prefix) and source_key[len(prefix) :]:
            return source_key[len(prefix) :]
        return PostRecord().record_id

    def _build_sync_payload(self, meta: FolderMeta, local_post: LocalPost) -> dict:
        absolute_path = Path(local_post.absolute_path)
        encoded_file = base64.b64encode(absolute_path.read_bytes()).decode("ascii")
        payload = {
            "wordpress_id": local_post.record.wordpress_id,
            "source_key": local_post.record.source_key,
            "source_path": local_post.relative_path,
            "post_type": meta.post_type,
            "taxonomy": meta.taxonomy,
            "term_name": local_post.category,
            "title": local_post.title,
            "slug": local_post.record.slug,
            "status": local_post.record.status,
            "content": local_post.record.content,
            "excerpt": local_post.record.excerpt,
            "meta": local_post.record.meta,
            "sync_checksum": local_post.sync_checksum,
            "image": {
                "filename": absolute_path.name,
                "mime_type": local_post.mime_type,
                "data_base64": encoded_file,
            },
        }
        if meta.enable_order:
            payload["menu_order"] = local_post.menu_order
        return payload

    def _determine_action(self, stored: PostRecord | None, local_post: LocalPost) -> str:
        if stored is None or not stored.wordpress_id:
            return "create"
        if self._is_order_only_change(stored, local_post):
            return "reorder"
        if stored.checksum != local_post.sync_checksum:
            return "update"
        return "unchanged"

    def _match_renamed_record(
        self,
        stored_posts: dict[str, PostRecord],
        unmatched_stored_paths: set[str],
        relative_path: str,
        file_checksum: str,
    ) -> str | None:
        relative_name = Path(relative_path).name
        relative_group = relative_directory_key(relative_path)
        relative_base_name = filename_without_order_prefix(relative_name).lower()

        candidates: list[str] = []
        for stored_path in unmatched_stored_paths:
            stored = stored_posts[stored_path]
            if relative_directory_key(stored_path) != relative_group:
                continue
            if filename_without_order_prefix(Path(stored_path).name).lower() != relative_base_name:
                continue
            if stored.file_checksum and stored.file_checksum != file_checksum:
                continue
            candidates.append(stored_path)

        if len(candidates) == 1:
            return candidates[0]
        return None

    def _resolve_download_relative_path(self, item: dict) -> str:
        source_path = str(item.get("source_path", "")).strip().replace("\\", "/")
        if source_path:
            return source_path

        category = self._category_from_export_item(item, "")
        extension = guess_extension_from_url(
            str(item.get("featured_image_url", "")),
            str(item.get("attachment_mime_type", "")),
        )
        filename = slugify(str(item.get("title", "post"))) or "post"
        return safe_relative_key(Path(sanitize_path_segment(category, "uncategorized")) / f"{filename}{extension}")

    def _category_from_export_item(self, item: dict, relative_path: str) -> str:
        terms = [str(term) for term in list(item.get("taxonomy_terms") or []) if str(term).strip()]
        if terms:
            return terms[0]
        if relative_path:
            return category_from_relative_path(relative_path)
        return "uncategorized"

    def _apply_order_updates(
        self,
        folder_path: str,
        meta: FolderMeta,
        client: WordPressClient,
        pending_order_updates: list[tuple[SyncAction, LocalPost]],
    ) -> list[SyncAction]:
        if not pending_order_updates:
            return []

        payload_posts = [
            {
                "id": local_post.record.wordpress_id,
                "menu_order": local_post.menu_order,
                "source_path": local_post.relative_path,
                "source_key": local_post.record.source_key,
                "sync_checksum": local_post.sync_checksum,
            }
            for _action, local_post in pending_order_updates
            if local_post.record.wordpress_id
        ]
        response_items = client.update_post_orders(meta.taxonomy, payload_posts)
        response_by_id: dict[int, dict] = {}
        for item in response_items:
            item_id = self._coerce_int(item.get("id"))
            if item_id is not None:
                response_by_id[item_id] = item

        results: list[SyncAction] = []
        for action, local_post in pending_order_updates:
            updated_record = local_post.record
            response_item = response_by_id.get(updated_record.wordpress_id or 0, {})
            previous_relative_path = local_post.stored_relative_path
            updated_record.menu_order = local_post.menu_order
            updated_record.file_checksum = local_post.file_checksum
            updated_record.checksum = local_post.sync_checksum
            updated_record.remote_modified_gmt = str(response_item.get("modified_gmt", updated_record.remote_modified_gmt))
            updated_record.source_key = str(response_item.get("source_key") or updated_record.source_key)
            if previous_relative_path and previous_relative_path != local_post.relative_path:
                meta.posts.pop(previous_relative_path, None)
            meta.posts[local_post.relative_path] = updated_record
            results.append(
                SyncAction(
                    action="reorder",
                    folder_path=folder_path,
                    relative_path=local_post.relative_path,
                    title=local_post.title,
                    message="Updated WordPress menu order.",
                    wordpress_id=updated_record.wordpress_id,
                )
            )

        return results

    def _apply_rename_plan(
        self,
        folder_path: Path,
        meta: FolderMeta,
        rename_plan: dict[str, str],
        action_name: str,
        message: str,
    ) -> list[SyncAction]:
        normalized_plan = {source: target for source, target in rename_plan.items() if source != target}
        if not normalized_plan:
            return []

        staged_moves: list[tuple[Path, Path, Path, str, str]] = []
        try:
            for index, (source_relative_path, target_relative_path) in enumerate(sorted(normalized_plan.items())):
                source_path = folder_path / Path(source_relative_path)
                target_path = folder_path / Path(target_relative_path)
                if not source_path.exists():
                    raise FileNotFoundError(f"Could not find file to rename: {source_relative_path}")
                if target_path.exists() and target_relative_path not in normalized_plan:
                    raise FileExistsError(f"Cannot rename to an existing file: {target_relative_path}")

                temp_path = source_path.with_name(f".{source_path.stem}.wp-sync-tmp-{index}{source_path.suffix}")
                while temp_path.exists():
                    temp_path = source_path.with_name(f".{source_path.stem}.wp-sync-tmp-{index + len(staged_moves) + 1}{source_path.suffix}")

                source_path.rename(temp_path)
                staged_moves.append((temp_path, source_path, target_path, source_relative_path, target_relative_path))

            for temp_path, _source_path, target_path, _source_relative_path, _target_relative_path in staged_moves:
                ensure_directory(target_path.parent)
                temp_path.rename(target_path)
        except Exception:
            for temp_path, source_path, target_path, _source_relative_path, _target_relative_path in reversed(staged_moves):
                try:
                    if temp_path.exists():
                        temp_path.rename(source_path)
                    elif target_path.exists() and not source_path.exists():
                        target_path.rename(source_path)
                except OSError:
                    pass
            raise

        updated_records: dict[str, PostRecord] = {}
        actions: list[SyncAction] = []
        for _temp_path, _source_path, target_path, source_relative_path, target_relative_path in staged_moves:
            record = meta.posts.pop(source_relative_path, PostRecord())
            updated_records[target_relative_path] = record
            actions.append(
                SyncAction(
                    action=action_name,
                    folder_path=str(folder_path),
                    relative_path=target_relative_path,
                    title=record.title or format_title_from_filename(target_path.name),
                    message=message,
                    wordpress_id=record.wordpress_id,
                )
            )

        meta.posts.update(updated_records)
        return actions

    def _build_order_target_relative_path(self, order_group: str, relative_path: str, menu_order: int, width: int) -> str:
        target_filename = build_numbered_filename(Path(relative_path).name, menu_order, width)
        if order_group:
            return safe_relative_key(Path(order_group) / target_filename)
        return target_filename

    def _is_order_only_change(self, stored: PostRecord, local_post: LocalPost) -> bool:
        path_changed = bool(local_post.stored_relative_path and local_post.stored_relative_path != local_post.relative_path)
        order_changed = stored.menu_order != local_post.menu_order
        if not path_changed and not order_changed:
            return False

        return (
            stored.title == local_post.title
            and stored.category == local_post.category
            and stored.slug == local_post.record.slug
            and stored.status == local_post.record.status
            and stored.content == local_post.record.content
            and stored.excerpt == local_post.record.excerpt
            and stored.meta == local_post.record.meta
            and stored.file_checksum in {"", local_post.file_checksum}
        )

    def _local_post_order_key(self, local_post: LocalPost) -> tuple[int, int, str]:
        filename = Path(local_post.relative_path).name
        has_prefix = has_menu_order_prefix(filename)
        return (0 if has_prefix else 1, local_post.menu_order, filename.lower())

    def _sort_actions(self, actions: list[SyncAction]) -> list[SyncAction]:
        order = {"error": 0, "conflict": 1, "create": 2, "update": 3, "reorder": 4, "delete": 5, "download": 6, "prune": 7, "unchanged": 8}
        return sorted(actions, key=lambda item: (order.get(item.action, 99), item.relative_path.lower()))

    def _coerce_int(self, value: object) -> int | None:
        if value in (None, ""):
            return None
        return int(value)