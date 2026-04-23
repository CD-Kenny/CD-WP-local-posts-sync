# WordPress Post Uploader

This project is a native-Python desktop tool for syncing local image folders with WordPress posts or custom post types. It uses only the Python standard library on the desktop side and includes a companion WordPress plugin that exposes the REST endpoints needed for create, update, delete, and export operations.

## Features

- Manage multiple WordPress site profiles in `profile.json`, keyed by website domain.
- Configure one or more local sync folders per site profile.
- Auto-create and maintain a `meta.json` file in every configured sync folder.
- Derive post titles from image file names.
- Derive categories from subfolder names.
- Upload, update, and delete WordPress posts based on folder changes.
- Download posts from WordPress back into the local folder for editing.
- Support custom post types and configurable taxonomies.
- Preview sync actions before uploading.

## Folder Rules

Local folders are scanned recursively for image files:

- `.jpg`
- `.jpeg`
- `.png`
- `.gif`
- `.webp`
- `.bmp`

The first folder segment under the sync root becomes the category or taxonomy term unless overridden in `meta.json`.

Example:

```text
posts/
  digital/
    1-post-title.jpg
```

This becomes:

- Title: `post title`
- Category: `digital`

If `digital/1-post-title.jpg` is removed locally, the next sync deletes the corresponding WordPress post and removes its tracking entry from `meta.json`.

## WordPress Authentication

The desktop app expects these values in `profile.json`:

- `site_url`
- `username`
- `password`

Use a WordPress Application Password as the `password` value. That keeps the desktop app compatible with native WordPress REST authentication over HTTPS without needing another Python dependency.

To create an application password in WordPress:

1. Log in to WordPress as a user that can edit the target post type.
2. Open your user profile in the WordPress admin area.
3. Create a new Application Password.
4. Copy that value into `profile.json` or the desktop form.

## Desktop Setup

Use Python 3.14.0.

Run the application from the project root:

```powershell
python main.py
```

On first launch, the app creates `profile.json` in the project root if it does not already exist.

For source runs, `profile.json` stays in the project root.

For packaged Windows installs, `profile.json` is stored in:

```text
%LOCALAPPDATA%\WordPressPostUploader\profile.json
```

That change is intentional because MSI installs typically live under `Program Files`, which is not a writable location for normal users.

## `profile.json` format

Example:

```json
{
  "active_domain": "example.com",
  "profiles": {
    "example.com": {
      "site_url": "https://example.com",
      "username": "editor",
      "password": "xxxx xxxx xxxx xxxx xxxx xxxx",
      "folders": [
        {
          "path": "C:/content/posts",
          "enabled": true
        }
      ]
    }
  }
}
```

## `meta.json` format

Every sync folder gets a `meta.json` in its root. The app creates it automatically if it is missing.

Example:

```json
{
  "folder_name": "Catalog Uploads",
  "folder_key": "catalog-uploads",
  "post_type": "post",
  "taxonomy": "category",
  "default_status": "draft",
  "default_content": "",
  "default_excerpt": "",
  "default_meta": {},
  "posts": {
    "digital/1-post-title.jpg": {
      "title": "post title",
      "content": "",
      "excerpt": "",
      "slug": "post-title",
      "status": "draft",
      "category": "digital",
      "wordpress_id": 123,
      "attachment_id": 456,
      "checksum": "...",
      "source_key": "catalog-uploads:digital/1-post-title.jpg",
      "remote_modified_gmt": "2026-04-22 12:00:00",
      "featured_image_url": "https://example.com/wp-content/uploads/...jpg",
      "mime_type": "image/jpeg",
      "meta": {}
    }
  }
}
```

The `posts` section doubles as sync state. It stores the WordPress IDs, checksums, and remote references needed to keep uploads and deletions in sync.

## How Sync Works

1. The app loads `profile.json` from the project root.
2. It loads every referenced folder and its `meta.json`.
3. A preview compares local image files to the stored sync state.
4. New files become create actions.
5. Changed files become update actions.
6. Removed files become delete actions.
7. Results are written back into each folder's `meta.json`.

## Downloading From WordPress

The `Download Selected` and `Download All` buttons call the plugin export endpoint, download featured images, and rebuild `meta.json` entries locally. If the plugin has a stored `source_path`, the app reuses it. Otherwise it creates a new file path using the first taxonomy term and the post title.

## WordPress Plugin

The companion plugin lives in [wordpress-plugin/wp-local-sync/wp-local-sync.php](wordpress-plugin/wp-local-sync/wp-local-sync.php).

Install it by copying the `wp-local-sync` folder into your WordPress site's `wp-content/plugins/` directory and then activating it in the WordPress admin area.

The plugin provides these endpoints:

- `GET /wp-json/wp-local-sync/v1/status`
- `GET /wp-json/wp-local-sync/v1/terms`
- `POST /wp-json/wp-local-sync/v1/sync-post`
- `DELETE /wp-json/wp-local-sync/v1/posts/<id>`
- `GET /wp-json/wp-local-sync/v1/export`

## Notes and Limits

- The companion plugin expects the target post type to exist.
- The user account used for authentication must be allowed to edit the target post type.
- The desktop app stores credentials in plain text inside `profile.json`. Keep that file private.
- Large images are sent as base64 JSON payloads, which is simple and dependency-free but not as efficient as a multipart upload workflow.
- The Windows package is self-contained and bundles its own Python runtime, so the target PC does not need Python installed. It is not a truly statically linked CPython binary, because that is not the normal Windows distribution model for Tkinter desktop apps.

## Building an MSI

The repository includes a Windows build script at [build-msi.ps1](build-msi.ps1) and a cx_Freeze setup script at [freeze_setup.py](freeze_setup.py).

What the packaging flow does:

- Bundles the desktop app and Python runtime into a Windows GUI executable.
- Builds an `.msi` installer from that frozen application.
- Excludes the `wordpress-plugin` folder entirely.
- Generates Windows branding assets from [assets/logo.svg](assets/logo.svg) for the app and installer.
- Applies Casual Development publisher and installer metadata.
- Installs per-user by default under your local app-data programs directory, so admin rights are usually not required.

Run the packager from PowerShell in the project root:

```powershell
./build-msi.ps1
```

If you want a clean rebuild:

```powershell
./build-msi.ps1 -Clean
```

The script uses the project's virtual environment by default:

```text
.venv\Scripts\python.exe
```

You can override that if needed:

```powershell
./build-msi.ps1 -PythonExe C:\path\to\python.exe
```

The generated installer is written to `dist\`.

Generated branding assets are written to `assets\generated\`. They are created from [assets/logo.svg](assets/logo.svg) automatically during the build. If those generated files already exist, the build can usually run without Inkscape. Inkscape is only needed when the SVG changes or the generated icon files are missing.

### Code Signing

The build script supports Authenticode signing with `signtool.exe`. It auto-discovers `signtool.exe` from the Windows SDK if it is not already on `PATH`.

The simple rule is:

- If you already have a real code-signing certificate installed in Windows, use `./build-msi.ps1 -Sign`.
- If you have been given a `.pfx` certificate file, use `./build-msi.ps1 -CertificateFile ... -CertificatePassword ...`.
- If you only need local or internal testing, run `./setup-dev-code-signing.ps1 -TrustCurrentUser` once, then use `./build-msi.ps1 -Sign`.

In other words:

- `certificate store` means the certificate is already installed in Windows.
- `.pfx` means the certificate is in a file that the script loads directly.

Sign using a `.pfx` certificate:

```powershell
./build-msi.ps1 -CertificateFile C:\certs\casual-development.pfx -CertificatePassword "your-password"
```

Sign using a certificate already installed in the Windows certificate store:

```powershell
./build-msi.ps1 -CertificateThumbprint "0123456789ABCDEF0123456789ABCDEF01234567"
```

Create a local development certificate for testing on your own PC:

```powershell
./setup-dev-code-signing.ps1 -TrustCurrentUser
./build-msi.ps1 -Sign
```

Optional signing parameters:

- `-SignToolPath` to point at a specific `signtool.exe`
- `-CertificateSubject` to sign by subject name instead of thumbprint
- `-TimestampUrl` to override the RFC3161 timestamp server
- `-NoTimestamp` to disable timestamping entirely
- `-Description` and `-DescriptionUrl` to customize the signer description metadata

When signing is enabled, the script signs the frozen Windows binaries first and then signs the final MSI.

For public distribution to other Windows PCs, you still need a certificate issued by a trusted certificate authority. The development helper script creates a self-signed certificate, which is only appropriate for local or controlled internal environments.

## Recommended Workflow

1. Install and activate the plugin.
2. Create an application password for your WordPress user.
3. Start the desktop app.
4. Add a profile for your website.
5. Add one or more sync folders.
6. Adjust each folder's `post_type`, `taxonomy`, and `default_status`.
7. Click `Preview Selected` to inspect the plan.
8. Click `Sync Selected` or `Sync All`.
9. Use `Download Selected` if you want the WordPress copy pulled back into the local folder.