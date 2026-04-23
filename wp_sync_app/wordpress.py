"""Minimal WordPress REST client for the companion plugin endpoints."""

from __future__ import annotations

import base64
import json

from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .utils import normalize_site_url


class WordPressError(RuntimeError):
    """Raised when the WordPress site or plugin returns an error."""


class WordPressClient:
    """Talk to the companion plugin using application-password HTTP Basic Auth."""

    def __init__(self, site_url: str, username: str, password: str) -> None:
        self.site_url = normalize_site_url(site_url)
        self.username = username.strip()
        self.password = password.strip()

        if not self.site_url:
            raise WordPressError("WordPress site URL is required.")
        if not self.username:
            raise WordPressError("WordPress username is required.")
        if not self.password:
            raise WordPressError("WordPress password or application password is required.")

    @property
    def api_base(self) -> str:
        return f"{self.site_url}/wp-json/wp-local-sync/v1"

    def check_connection(self) -> dict[str, Any]:
        response = self._request_json("GET", "status")
        if not isinstance(response, dict):
            raise WordPressError("Unexpected status response from WordPress.")
        return response

    def list_terms(self, taxonomy: str) -> list[dict[str, Any]]:
        response = self._request_json("GET", "terms", query={"taxonomy": taxonomy})
        if not isinstance(response, dict):
            raise WordPressError("Unexpected terms response from WordPress.")
        return list(response.get("terms") or [])

    def sync_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json("POST", "sync-post", payload=payload)
        if not isinstance(response, dict):
            raise WordPressError("Unexpected post sync response from WordPress.")
        return response

    def delete_post(self, post_id: int) -> dict[str, Any]:
        response = self._request_json("DELETE", f"posts/{post_id}")
        if not isinstance(response, dict):
            raise WordPressError("Unexpected delete response from WordPress.")
        return response

    def get_admin_post_edit_link(self, post_id: int) -> str:
        response = self._request_json("GET", f"posts/{post_id}/admin-link")
        if not isinstance(response, dict):
            raise WordPressError("Unexpected admin link response from WordPress.")
        url = str(response.get("url", "")).strip()
        if not url:
            raise WordPressError("WordPress did not return an admin edit link.")
        return url

    def update_post_orders(self, taxonomy: str, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        response = self._request_json("POST", "posts/order", payload={"taxonomy": taxonomy, "posts": posts})
        if not isinstance(response, dict):
            raise WordPressError("Unexpected order update response from WordPress.")
        return list(response.get("posts") or [])

    def export_posts(self, post_type: str, taxonomy: str) -> list[dict[str, Any]]:
        response = self._request_json("GET", "export", query={"post_type": post_type, "taxonomy": taxonomy})
        if not isinstance(response, dict):
            raise WordPressError("Unexpected export response from WordPress.")
        return list(response.get("posts") or [])

    def download_binary(self, absolute_url: str) -> bytes:
        body = self._request_raw("GET", absolute_url=absolute_url)
        return body

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        raw = self._request_raw(method, path=path, payload=payload, query=query)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WordPressError("WordPress returned invalid JSON.") from exc

    def _request_raw(
        self,
        method: str,
        path: str = "",
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        absolute_url: str | None = None,
    ) -> bytes:
        url = absolute_url or f"{self.api_base}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query, doseq=True)}"

        headers = {
            "Authorization": f"Basic {self._build_basic_auth_token()}",
            "Accept": "application/json" if absolute_url is None else "*/*",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url=url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=120) as response:
                return response.read()
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise WordPressError(self._format_http_error(exc.code, error_body)) from exc
        except URLError as exc:
            raise WordPressError(f"Could not reach {self.site_url}: {exc.reason}") from exc

    def _build_basic_auth_token(self) -> str:
        raw = f"{self.username}:{self.password}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _format_http_error(self, status_code: int, error_body: str) -> str:
        try:
            parsed = json.loads(error_body)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            message = parsed.get("message") or parsed.get("code") or error_body
            return f"WordPress returned HTTP {status_code}: {message}"
        if error_body:
            return f"WordPress returned HTTP {status_code}: {error_body}"
        return f"WordPress returned HTTP {status_code}."