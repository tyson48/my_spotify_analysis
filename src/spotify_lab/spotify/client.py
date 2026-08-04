"""Shared HTTP client for authenticated Spotify Web API requests."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Protocol

API_BASE_URL = "https://api.spotify.com/v1"

QueryValue = str | int | float | bool | None


class AccessTokenProvider(Protocol):
    """Anything capable of returning a current Spotify access token."""

    def get_access_token(self, *, force_login: bool = False) -> str: ...


class SpotifyAPIError(RuntimeError):
    """An error returned by, or encountered while calling, the Spotify API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class SpotifyClient:
    """Make authenticated requests to the Spotify Web API.

    The client owns only the shared HTTP concerns: constructing URLs, obtaining
    a valid token, adding headers, encoding parameters and turning Spotify error
    responses into ``SpotifyAPIError``. Resource-specific endpoint paths belong
    in modules such as ``users.py``.
    """

    def __init__(self, token_provider: AccessTokenProvider) -> None:
        """Create a client backed by an OAuth token provider.

        ``SpotifyOAuth`` implements the required protocol and transparently
        refreshes an expired access token before each request.
        """
        self._token_provider = token_provider

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
    ) -> Any:
        """Send a GET request to retrieve resources and return its decoded JSON response."""
        return self.request("GET", path, params=params)

    def post(
        self,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send a POST request to create resources and return its decoded JSON response."""
        return self.request("POST", path, params=params, json_body=json_body)

    def put(
        self,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send a PUT request to change and/or replace resources and return its decoded JSON response."""
        return self.request("PUT", path, params=params, json_body=json_body)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        """Send an authenticated request to a path below Spotify API ``/v1``.

        Args:
            method: HTTP method such as ``GET``, ``POST`` or ``PUT``.
            path: Endpoint path relative to ``/v1``, such as ``/me``.
            params: Optional query parameters. Values set to ``None`` are omitted.
            json_body: Optional object serialized as the JSON request body.

        Returns:
            The decoded JSON value, or ``None`` for an empty response.

        Raises:
            ValueError: If ``path`` is an absolute URL rather than an API path.
            SpotifyAPIError: If Spotify rejects the request, returns malformed
                JSON, or cannot be reached. For HTTP 429, ``retry_after`` contains
                Spotify's suggested waiting time when the header is available.
        """
        url = self._build_url(path, params)
        body = json.dumps(json_body).encode() if json_body is not None else None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token_provider.get_access_token()}",
            "User-Agent": "my-spotify-analysis/0.1.0",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read()
        except urllib.error.HTTPError as error:
            raise self._api_error(error) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SpotifyAPIError(f"Could not reach Spotify: {error}") from error

        if not response_body:
            return None
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise SpotifyAPIError("Spotify returned a non-JSON API response.") from error

    @staticmethod
    def _build_url(path: str, params: Mapping[str, QueryValue] | None) -> str:
        """Build a safe API URL and omit unset query parameters."""
        parsed = urllib.parse.urlparse(path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("Spotify API paths must be relative, not absolute URLs.")

        url = f"{API_BASE_URL}/{path.lstrip('/')}"
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None}
            )
            if query:
                url = f"{url}?{query}"
        return url

    @staticmethod
    def _api_error(error: urllib.error.HTTPError) -> SpotifyAPIError:
        """Extract Spotify's message and rate-limit metadata from an HTTP error."""
        message = f"Spotify API request failed with HTTP {error.code}."
        try:
            payload = json.loads(error.read())
            details = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(details, dict) and isinstance(details.get("message"), str):
                message = details["message"]
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        retry_after = None
        retry_header = error.headers.get("Retry-After") if error.headers else None
        if retry_header:
            with suppress(ValueError):
                retry_after = int(retry_header)
        return SpotifyAPIError(message, status=error.code, retry_after=retry_after)
