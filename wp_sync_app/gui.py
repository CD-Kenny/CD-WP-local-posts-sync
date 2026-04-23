"""Tkinter user interface for profile management and WordPress sync operations."""

from __future__ import annotations

from contextlib import suppress
import os
import queue
import threading
import tkinter as tk
import webbrowser

from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import ConfigError, FolderMetaStore, ProfileStore
from .models import AppProfiles, FolderMeta, FolderReference, SiteProfile, SyncAction
from .sync_engine import FolderSyncService
from .utils import domain_from_site_url, resolve_asset_path
from .wordpress import WordPressClient


class WordPressUploaderApp:
    """Desktop UI for managing profiles, folders, and sync actions."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Casual Development WordPress Post Uploader")
        self.root.geometry("1280x820")
        self.root.minsize(1120, 720)
        self.window_icon: tk.PhotoImage | None = None

        self._configure_window_icon()

        self.profile_store = ProfileStore()
        self.folder_meta_store = FolderMetaStore()
        self.sync_service = FolderSyncService(self.folder_meta_store)
        self.app_profiles = self._load_profiles()
        self.folder_meta_cache: dict[str, FolderMeta] = {}
        self.current_task: threading.Thread | None = None
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.domain_var = tk.StringVar()
        self.site_url_var = tk.StringVar()
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.folder_name_var = tk.StringVar()
        self.folder_key_var = tk.StringVar()
        self.post_type_var = tk.StringVar(value="post")
        self.taxonomy_var = tk.StringVar(value="category")
        self.default_status_var = tk.StringVar(value="draft")
        self.enable_order_var = tk.BooleanVar(value=True)

        self.folder_paths: list[str] = []
        self.order_tabs: dict[str, dict[str, object]] = {}
        self.order_drag_group: str | None = None
        self.order_drag_index: int | None = None

        self._build_ui()
        self._load_initial_profile()
        self._log(f"Profile storage path: {self.profile_store.path}")
        self.root.after(150, self._poll_worker_queue)

    def _configure_window_icon(self) -> None:
        png_path = resolve_asset_path("generated", "logo-64.png")
        ico_path = resolve_asset_path("generated", "logo.ico")

        if png_path.exists():
            with suppress(tk.TclError):
                self.window_icon = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self.window_icon)
                return

        if ico_path.exists():
            with suppress(tk.TclError):
                self.root.iconbitmap(default=str(ico_path))

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill="both", expand=True)
        main_frame.columnconfigure(0, weight=0)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(main_frame)
        left_panel.grid(row=0, column=0, sticky="nsw", padx=(0, 12))

        right_panel = ttk.Frame(main_frame)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(1, weight=1)
        right_panel.rowconfigure(2, weight=1)

        self._build_profile_section(left_panel)
        self._build_folder_section(left_panel)
        self._build_folder_meta_section(left_panel)
        self._build_actions_section(right_panel)
        self._build_plan_section(right_panel)
        self._build_log_section(right_panel)

    def _build_profile_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Profile", padding=10)
        section.pack(fill="x", pady=(0, 12))
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Domain").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.domain_combo = ttk.Combobox(section, textvariable=self.domain_var, state="normal")
        self.domain_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.domain_combo.bind("<<ComboboxSelected>>", self._on_domain_selected)

        ttk.Label(section, text="Site URL").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.site_url_var).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Username").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.username_var).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Password").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.password_var, show="*").grid(row=3, column=1, sticky="ew", pady=4)

        button_row = ttk.Frame(section)
        button_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for index in range(4):
            button_row.columnconfigure(index, weight=1)
        ttk.Button(button_row, text="New Profile", command=self._new_profile).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="Save Profile", command=self._save_profile).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(button_row, text="Test Connection", command=self._test_connection).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(button_row, text="Open Config Folder", command=self._open_profile_storage).grid(row=0, column=3, sticky="ew", padx=(4, 0))

        hint = (
            "Use a WordPress Application Password here. The companion plugin provides the sync endpoints, "
            "but authentication should still use your WordPress username and application password. "
            "Installed Windows builds store profile.json in your local app-data folder."
        )
        ttk.Label(section, text=hint, wraplength=330, justify="left").grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )

    def _build_folder_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Sync Folders", padding=10)
        section.pack(fill="both", expand=True, pady=(0, 12))

        self.folder_listbox = tk.Listbox(section, height=10, exportselection=False)
        self.folder_listbox.pack(fill="both", expand=True)
        self.folder_listbox.bind("<<ListboxSelect>>", self._on_folder_selected)

        button_row = ttk.Frame(section)
        button_row.pack(fill="x", pady=(8, 0))
        for index in range(4):
            button_row.columnconfigure(index, weight=1)
        ttk.Button(button_row, text="Add Folder", command=self._add_folder).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="Remove Folder", command=self._remove_selected_folder).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(button_row, text="Open Folder", command=self._open_selected_folder).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(button_row, text="Open Meta", command=self._open_selected_meta).grid(row=0, column=3, sticky="ew", padx=(4, 0))

    def _build_folder_meta_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Selected Folder Metadata", padding=10)
        section.pack(fill="x")
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Folder Name").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.folder_name_var).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Folder Key").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.folder_key_var).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Post Type").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.post_type_var).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Taxonomy").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(section, textvariable=self.taxonomy_var).grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(section, text="Default Status").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Combobox(
            section,
            textvariable=self.default_status_var,
            values=["draft", "publish", "pending", "private"],
            state="readonly",
        ).grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Checkbutton(
            section,
            text="Enable filename-based menu order",
            variable=self.enable_order_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ttk.Button(section, text="Save Folder Meta", command=self._save_selected_folder_meta).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

    def _build_actions_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Operations", padding=10)
        section.grid(row=0, column=0, sticky="ew")
        for index in range(7):
            section.columnconfigure(index, weight=1)

        ttk.Button(section, text="Preview Selected", command=self._preview_selected_folder).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(section, text="Sync Selected", command=self._sync_selected_folder).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(section, text="Sync All", command=self._sync_all_folders).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(section, text="Download Selected", command=self._download_selected_folder).grid(row=0, column=3, sticky="ew", padx=4)
        ttk.Button(section, text="Download All", command=self._download_all_folders).grid(row=0, column=4, sticky="ew", padx=(4, 0))
        ttk.Button(section, text="Number Unnumbered", command=self._number_selected_folder_files).grid(row=0, column=5, sticky="ew", padx=4)
        ttk.Button(section, text="Save Reorder", command=self._save_selected_order).grid(row=0, column=6, sticky="ew", padx=(4, 0))

    def _build_plan_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Preview / Results", padding=10)
        section.grid(row=1, column=0, sticky="nsew", pady=(12, 12))
        section.columnconfigure(0, weight=1)
        section.rowconfigure(0, weight=1)

        self.plan_notebook = ttk.Notebook(section)
        self.plan_notebook.grid(row=0, column=0, sticky="nsew")

        changes_frame = ttk.Frame(self.plan_notebook, padding=0)
        changes_frame.columnconfigure(0, weight=1)
        changes_frame.rowconfigure(0, weight=1)
        self.plan_notebook.add(changes_frame, text="Changes")

        columns = ("action", "folder", "path", "title", "message")
        self.plan_tree = ttk.Treeview(changes_frame, columns=columns, show="headings", height=16)
        self.plan_tree.grid(row=0, column=0, sticky="nsew")
        headings = {
            "action": "Action",
            "folder": "Folder",
            "path": "Relative Path",
            "title": "Title",
            "message": "Message",
        }
        widths = {"action": 100, "folder": 180, "path": 230, "title": 200, "message": 360}
        for column in columns:
            self.plan_tree.heading(column, text=headings[column])
            self.plan_tree.column(column, width=widths[column], anchor="w")

        scrollbar = ttk.Scrollbar(changes_frame, orient="vertical", command=self.plan_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.plan_tree.configure(yscrollcommand=scrollbar.set)

    def _build_log_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="Activity Log", padding=10)
        section.grid(row=2, column=0, sticky="nsew")
        section.columnconfigure(0, weight=1)
        section.rowconfigure(0, weight=1)

        self.log_text = tk.Text(section, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(section, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _load_profiles(self) -> AppProfiles:
        try:
            return self.profile_store.load()
        except ConfigError as exc:
            messagebox.showerror("Configuration Error", str(exc))
            return AppProfiles()

    def _load_initial_profile(self) -> None:
        self._refresh_domain_options()
        if self.app_profiles.active_domain and self.app_profiles.active_domain in self.app_profiles.profiles:
            self.domain_var.set(self.app_profiles.active_domain)
            self._load_profile(self.app_profiles.profiles[self.app_profiles.active_domain])
            return
        if self.app_profiles.profiles:
            first_domain = sorted(self.app_profiles.profiles)[0]
            self.domain_var.set(first_domain)
            self._load_profile(self.app_profiles.profiles[first_domain])
            return
        self._new_profile()

    def _refresh_domain_options(self) -> None:
        self.domain_combo["values"] = sorted(self.app_profiles.profiles)

    def _new_profile(self) -> None:
        self.domain_var.set("")
        self.site_url_var.set("")
        self.username_var.set("")
        self.password_var.set("")
        self.folder_paths = []
        self.folder_meta_cache.clear()
        self._refresh_folder_listbox()
        self._clear_folder_meta_fields()
        self._populate_plan([])
        self._refresh_order_tabs(None)
        self._log("Started a new empty profile.")

    def _save_profile(self, silent: bool = False) -> bool:
        domain = self.domain_var.get().strip()
        site_url = self.site_url_var.get().strip()
        if not domain:
            domain = domain_from_site_url(site_url)
            self.domain_var.set(domain)
        if not domain:
            if not silent:
                messagebox.showerror("Missing Domain", "Enter a site URL or a domain before saving the profile.")
            return False

        profile = SiteProfile(
            domain=domain,
            site_url=site_url,
            username=self.username_var.get().strip(),
            password=self.password_var.get().strip(),
            folders=[FolderReference(path=folder_path, enabled=True) for folder_path in self.folder_paths],
        )
        self.app_profiles.profiles[domain] = profile
        self.app_profiles.active_domain = domain
        try:
            self.profile_store.save(self.app_profiles)
        except ConfigError as exc:
            if not silent:
                messagebox.showerror("Save Error", str(exc))
            return False

        self._refresh_domain_options()
        if not silent:
            self._log(f"Saved profile for {domain} to {self.profile_store.path}.")
        return True

    def _test_connection(self) -> None:
        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return

        def task() -> dict:
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            return client.check_connection()

        self._run_in_background("Testing WordPress connection", task, self._handle_connection_result)

    def _add_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select a folder to sync")
        if not selected:
            return
        folder_path = str(Path(selected).resolve())
        if folder_path not in self.folder_paths:
            self.folder_paths.append(folder_path)
        try:
            self.folder_meta_cache[folder_path] = self.folder_meta_store.load(Path(folder_path))
        except ConfigError as exc:
            messagebox.showerror("Folder Error", str(exc))
            return
        self._refresh_folder_listbox(select_path=folder_path)
        self._save_profile(silent=True)
        self._log(f"Added sync folder: {folder_path}")

    def _remove_selected_folder(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            return
        self.folder_paths = [path for path in self.folder_paths if path != selected]
        self.folder_meta_cache.pop(selected, None)
        self._refresh_folder_listbox()
        self._clear_folder_meta_fields()
        self._save_profile(silent=True)
        self._log(f"Removed sync folder: {selected}")

    def _open_selected_folder(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            return
        if not Path(selected).exists():
            messagebox.showerror("Folder Missing", f"The folder no longer exists:\n{selected}")
            return
        os.startfile(selected)

    def _open_profile_storage(self) -> None:
        try:
            self.profile_store.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Config Error", f"Could not create config folder:\n{exc}")
            return
        os.startfile(str(self.profile_store.path.parent))

    def _open_selected_meta(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            return
        try:
            self.folder_meta_cache[selected] = self.folder_meta_store.load(Path(selected))
        except ConfigError as exc:
            messagebox.showerror("Metadata Error", str(exc))
            return
        os.startfile(str(Path(selected) / "meta.json"))

    def _save_selected_folder_meta(self, refresh_order_tabs: bool = True) -> bool:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return False
        meta = self._meta_from_fields()
        try:
            self.folder_meta_store.save(Path(selected), meta)
        except ConfigError as exc:
            messagebox.showerror("Metadata Error", str(exc))
            return False
        self.folder_meta_cache[selected] = meta
        if refresh_order_tabs:
            self._refresh_order_tabs(selected)
        self._log(f"Saved {selected}\\meta.json.")
        return True

    def _preview_selected_folder(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return
        if not self._save_selected_folder_meta():
            return
        meta = self.folder_meta_cache.get(selected)
        if meta is None:
            return
        try:
            results = self.sync_service.preview_sync(Path(selected), meta)
        except Exception as exc:
            messagebox.showerror("Preview Error", str(exc))
            return
        self._populate_plan(results)
        self._log(f"Previewed sync plan for {selected}.")

    def _sync_selected_folder(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return
        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return
        if not self._save_selected_folder_meta():
            return

        def task() -> list[SyncAction]:
            meta = self.folder_meta_cache[selected]
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            return self.sync_service.sync_folder(Path(selected), meta, client)

        self._run_in_background(f"Syncing {selected}", task, self._handle_sync_result)

    def _sync_all_folders(self) -> None:
        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return
        if not self.folder_paths:
            messagebox.showerror("No Folders", "Add at least one sync folder first.")
            return
        if not self._save_selected_folder_meta_if_any():
            return

        def task() -> list[SyncAction]:
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            all_actions: list[SyncAction] = []
            for folder_path in self.folder_paths:
                meta = self.folder_meta_cache[folder_path]
                all_actions.extend(self.sync_service.sync_folder(Path(folder_path), meta, client))
            return all_actions

        self._run_in_background("Syncing all configured folders", task, self._handle_sync_result)

    def _download_selected_folder(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return
        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return
        if not self._save_selected_folder_meta():
            return

        def task() -> list[SyncAction]:
            meta = self.folder_meta_cache[selected]
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            return self.sync_service.download_folder(Path(selected), meta, client)

        self._run_in_background(f"Downloading WordPress posts into {selected}", task, self._handle_sync_result)

    def _download_all_folders(self) -> None:
        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return
        if not self.folder_paths:
            messagebox.showerror("No Folders", "Add at least one sync folder first.")
            return
        if not self._save_selected_folder_meta_if_any():
            return

        def task() -> list[SyncAction]:
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            all_actions: list[SyncAction] = []
            for folder_path in self.folder_paths:
                meta = self.folder_meta_cache[folder_path]
                all_actions.extend(self.sync_service.download_folder(Path(folder_path), meta, client))
            return all_actions

        self._run_in_background("Downloading WordPress posts for all configured folders", task, self._handle_sync_result)

    def _run_in_background(self, description: str, task: callable, on_success: callable) -> None:
        if self.current_task and self.current_task.is_alive():
            messagebox.showinfo("Operation Running", "Wait for the current operation to finish before starting another one.")
            return

        self._log(description)

        def worker() -> None:
            try:
                result = task()
                self.worker_queue.put(("success", (description, result, on_success)))
            except Exception as exc:
                self.worker_queue.put(("error", (description, exc)))

        self.current_task = threading.Thread(target=worker, daemon=True)
        self.current_task.start()

    def _poll_worker_queue(self) -> None:
        while True:
            try:
                kind, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "success":
                description, result, on_success = payload
                self._log(f"Completed: {description}")
                on_success(result)
            else:
                description, exc = payload
                self._log(f"Failed: {description}: {exc}")
                messagebox.showerror("Operation Failed", str(exc))

        self.root.after(150, self._poll_worker_queue)

    def _handle_connection_result(self, result: dict) -> None:
        user = result.get("user") or result.get("username") or "authenticated user"
        message = result.get("message") or "Connection succeeded."
        self._log(f"WordPress connection verified as {user}.")
        messagebox.showinfo("Connection OK", message)

    def _handle_sync_result(self, actions: list[SyncAction]) -> None:
        self._populate_plan(actions)
        selected = self._get_selected_folder_path()
        self._refresh_order_tabs(selected)
        success_count = len([item for item in actions if item.action not in {"error", "unchanged"}])
        error_count = len([item for item in actions if item.action == "error"])
        self._log(f"Operation finished with {success_count} change(s) and {error_count} error(s).")

    def _populate_plan(self, actions: list[SyncAction]) -> None:
        self.plan_tree.delete(*self.plan_tree.get_children())
        for item in actions:
            folder_name = Path(item.folder_path).name if item.folder_path else ""
            self.plan_tree.insert(
                "",
                "end",
                values=(item.action, folder_name, item.relative_path, item.title, item.message),
            )

    def _on_domain_selected(self, _event: object | None = None) -> None:
        selected_domain = self.domain_var.get().strip()
        if selected_domain in self.app_profiles.profiles:
            self._load_profile(self.app_profiles.profiles[selected_domain])
            self._save_profile(silent=True)

    def _load_profile(self, profile: SiteProfile) -> None:
        self.domain_var.set(profile.domain)
        self.site_url_var.set(profile.site_url)
        self.username_var.set(profile.username)
        self.password_var.set(profile.password)
        self.folder_paths = [folder.path for folder in profile.folders if folder.path]
        self._reload_folder_meta_cache()
        self._refresh_folder_listbox()
        self.app_profiles.active_domain = profile.domain
        self._log(f"Loaded profile for {profile.domain}.")

    def _reload_folder_meta_cache(self) -> None:
        self.folder_meta_cache.clear()
        for folder_path in self.folder_paths:
            try:
                self.folder_meta_cache[folder_path] = self.folder_meta_store.load(Path(folder_path))
            except ConfigError as exc:
                self._log(str(exc))

    def _refresh_folder_listbox(self, select_path: str | None = None) -> None:
        self.folder_listbox.delete(0, tk.END)
        for folder_path in self.folder_paths:
            self.folder_listbox.insert(tk.END, folder_path)
        if select_path and select_path in self.folder_paths:
            index = self.folder_paths.index(select_path)
            self.folder_listbox.selection_clear(0, tk.END)
            self.folder_listbox.selection_set(index)
            self.folder_listbox.activate(index)
            self._load_selected_folder_meta(select_path)
            return
        if self.folder_paths:
            self.folder_listbox.selection_set(0)
            self._load_selected_folder_meta(self.folder_paths[0])
            return
        self._refresh_order_tabs(None)

    def _on_folder_selected(self, _event: object | None = None) -> None:
        selected = self._get_selected_folder_path()
        if selected:
            self._load_selected_folder_meta(selected)

    def _load_selected_folder_meta(self, folder_path: str) -> None:
        meta = self.folder_meta_cache.get(folder_path)
        if meta is None:
            try:
                meta = self.folder_meta_store.load(Path(folder_path))
            except ConfigError as exc:
                messagebox.showerror("Metadata Error", str(exc))
                return
            self.folder_meta_cache[folder_path] = meta

        self.folder_name_var.set(meta.folder_name)
        self.folder_key_var.set(meta.folder_key)
        self.post_type_var.set(meta.post_type)
        self.taxonomy_var.set(meta.taxonomy)
        self.default_status_var.set(meta.default_status)
        self.enable_order_var.set(meta.enable_order)
        self._refresh_order_tabs(folder_path)

    def _clear_folder_meta_fields(self) -> None:
        self.folder_name_var.set("")
        self.folder_key_var.set("")
        self.post_type_var.set("post")
        self.taxonomy_var.set("category")
        self.default_status_var.set("draft")
        self.enable_order_var.set(True)

    def _meta_from_fields(self) -> FolderMeta:
        selected = self._get_selected_folder_path()
        existing = self.folder_meta_cache.get(selected or "", FolderMeta())
        return FolderMeta(
            folder_name=self.folder_name_var.get().strip() or existing.folder_name,
            folder_key=self.folder_key_var.get().strip() or existing.folder_key,
            post_type=self.post_type_var.get().strip() or existing.post_type,
            taxonomy=self.taxonomy_var.get().strip() or existing.taxonomy,
            default_status=self.default_status_var.get().strip() or existing.default_status,
            enable_order=self.enable_order_var.get(),
            default_content=existing.default_content,
            default_excerpt=existing.default_excerpt,
            default_meta=existing.default_meta,
            posts=existing.posts,
        )

    def _refresh_order_tabs(self, folder_path: str | None) -> None:
        if not hasattr(self, "plan_notebook"):
            return

        for tab_id in list(self.plan_notebook.tabs())[1:]:
            self.plan_notebook.forget(tab_id)

        self.order_tabs.clear()
        self.order_drag_group = None
        self.order_drag_index = None

        if not folder_path:
            return

        meta = self.folder_meta_cache.get(folder_path)
        if meta is None or not meta.enable_order:
            return

        try:
            grouped_posts = self.sync_service.list_ordered_posts(Path(folder_path), meta)
        except Exception as exc:
            self._log(f"Could not load order tabs for {folder_path}: {exc}")
            return

        for order_group, posts in grouped_posts.items():
            tab_frame = ttk.Frame(self.plan_notebook, padding=10)
            tab_frame.columnconfigure(0, weight=1)
            tab_frame.rowconfigure(0, weight=1)

            listbox = tk.Listbox(tab_frame, exportselection=False, activestyle="none")
            listbox.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(tab_frame, orient="vertical", command=listbox.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            listbox.configure(yscrollcommand=scrollbar.set)

            hint = ttk.Label(tab_frame, text="Drag files to reorder them. Save Reorder renames the files and updates WordPress.")
            hint.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

            listbox.bind("<ButtonPress-1>", lambda event, key=order_group: self._on_order_listbox_press(key, event))
            listbox.bind("<B1-Motion>", lambda event, key=order_group: self._on_order_listbox_drag(key, event))
            listbox.bind("<ButtonRelease-1>", self._on_order_listbox_release)
            listbox.bind("<Double-Button-1>", lambda event, key=order_group: self._on_order_listbox_double_click(key, event))

            self.plan_notebook.add(tab_frame, text=self._order_group_label(order_group))
            self.order_tabs[order_group] = {
                "listbox": listbox,
                "paths": [post.relative_path for post in posts],
                "posts_by_path": {post.relative_path: post for post in posts},
            }
            self._populate_order_listbox(order_group)

    def _populate_order_listbox(self, order_group: str) -> None:
        state = self.order_tabs.get(order_group)
        if not state:
            return

        listbox = state["listbox"]
        paths = state["paths"]
        listbox.delete(0, tk.END)
        for index, relative_path in enumerate(paths, start=1):
            listbox.insert(tk.END, f"{index:02d}  {Path(relative_path).name}")

    def _order_group_label(self, order_group: str) -> str:
        return order_group or "Root"

    def _on_order_listbox_press(self, order_group: str, event: tk.Event) -> None:
        state = self.order_tabs.get(order_group)
        if not state:
            return

        listbox = state["listbox"]
        if listbox.size() == 0:
            return

        index = max(0, min(listbox.size() - 1, listbox.nearest(event.y)))
        self.order_drag_group = order_group
        self.order_drag_index = index
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(index)
        listbox.activate(index)

    def _on_order_listbox_drag(self, order_group: str, event: tk.Event) -> None:
        if self.order_drag_group != order_group or self.order_drag_index is None:
            return

        state = self.order_tabs.get(order_group)
        if not state:
            return

        listbox = state["listbox"]
        if listbox.size() == 0:
            return

        new_index = max(0, min(listbox.size() - 1, listbox.nearest(event.y)))
        if new_index == self.order_drag_index:
            return

        paths = state["paths"]
        moved_path = paths.pop(self.order_drag_index)
        paths.insert(new_index, moved_path)
        self.order_drag_index = new_index
        self._populate_order_listbox(order_group)
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(new_index)
        listbox.activate(new_index)

    def _on_order_listbox_release(self, _event: tk.Event) -> None:
        self.order_drag_group = None
        self.order_drag_index = None

    def _on_order_listbox_double_click(self, order_group: str, event: tk.Event) -> None:
        state = self.order_tabs.get(order_group)
        if not state:
            return

        listbox = state["listbox"]
        if listbox.size() == 0:
            return

        index = max(0, min(listbox.size() - 1, listbox.nearest(event.y)))
        relative_path = state["paths"][index]
        local_post = state["posts_by_path"].get(relative_path)
        if local_post is None or not local_post.record.wordpress_id:
            messagebox.showinfo("Not Synced Yet", "This file does not have a linked WordPress post yet.")
            return

        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            return

        post_id = local_post.record.wordpress_id
        title = local_post.title or Path(relative_path).name

        def task() -> str:
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            return client.get_admin_post_edit_link(post_id)

        self._run_in_background(
            f"Opening WordPress admin editor for {title}",
            task,
            lambda url, post_title=title: self._handle_admin_edit_link(url, post_title),
        )

    def _handle_admin_edit_link(self, url: str, title: str) -> None:
        webbrowser.open(url, new=2)
        self._log(f"Opened WordPress admin editor for {title}.")

    def _number_selected_folder_files(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return

        if not self._save_selected_folder_meta():
            return
        meta = self.folder_meta_cache.get(selected)
        if meta is None:
            return
        if not meta.enable_order:
            messagebox.showinfo("Ordering Disabled", "Enable folder ordering before numbering files.")
            return

        try:
            actions = self.sync_service.number_unnumbered_files(Path(selected), meta)
        except Exception as exc:
            messagebox.showerror("Numbering Error", str(exc))
            return

        self.folder_meta_cache[selected] = meta
        self._populate_plan(actions)
        self._refresh_order_tabs(selected)
        if actions:
            self._log(f"Added number prefixes to {len(actions)} file(s) in {selected}.")
            return
        self._log(f"No numbering changes were needed in {selected}.")

    def _save_selected_order(self) -> None:
        selected = self._get_selected_folder_path()
        if not selected:
            messagebox.showerror("No Folder Selected", "Select a sync folder first.")
            return

        desired_orders = {group: list(state["paths"]) for group, state in self.order_tabs.items()}
        if not self._save_selected_folder_meta(refresh_order_tabs=False):
            return
        meta = self.folder_meta_cache.get(selected)
        if meta is None:
            return
        if not meta.enable_order:
            messagebox.showinfo("Ordering Disabled", "Enable folder ordering before saving a reorder.")
            return

        local_actions: list[SyncAction] = []
        try:
            current_groups = self.sync_service.list_ordered_posts(Path(selected), meta)
            for order_group, posts in current_groups.items():
                current_paths = [post.relative_path for post in posts]
                desired_paths = desired_orders.get(order_group, current_paths)
                if desired_paths != current_paths:
                    local_actions.extend(
                        self.sync_service.reorder_category_posts(Path(selected), meta, order_group, desired_paths)
                    )
        except Exception as exc:
            messagebox.showerror("Reorder Error", str(exc))
            return

        self.folder_meta_cache[selected] = meta
        self._refresh_order_tabs(selected)

        profile = self._build_profile_from_fields(require_url=True)
        if not profile:
            if local_actions:
                self._populate_plan(local_actions)
                self._log(f"Saved local order changes in {selected}, but WordPress was not updated.")
            return

        def task() -> list[SyncAction]:
            client = WordPressClient(profile.site_url, profile.username, profile.password)
            remote_actions = self.sync_service.save_order_changes(Path(selected), meta, client)
            return local_actions + remote_actions

        self._run_in_background(f"Saving reorder for {selected}", task, self._handle_sync_result)

    def _build_profile_from_fields(self, require_url: bool) -> SiteProfile | None:
        site_url = self.site_url_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        domain = self.domain_var.get().strip() or domain_from_site_url(site_url)
        if require_url and not site_url:
            messagebox.showerror("Missing Site URL", "Enter the WordPress site URL first.")
            return None
        if require_url and not username:
            messagebox.showerror("Missing Username", "Enter the WordPress username first.")
            return None
        if require_url and not password:
            messagebox.showerror("Missing Password", "Enter the WordPress password or application password first.")
            return None
        return SiteProfile(domain=domain, site_url=site_url, username=username, password=password)

    def _save_selected_folder_meta_if_any(self) -> bool:
        if self._get_selected_folder_path():
            return self._save_selected_folder_meta()
        return True

    def _get_selected_folder_path(self) -> str | None:
        selection = self.folder_listbox.curselection()
        if not selection:
            return None
        return self.folder_paths[selection[0]]

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")