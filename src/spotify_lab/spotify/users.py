"""Endpoints that operate on the currently authorized Spotify user."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from spotify_lab.spotify.client import SpotifyClient

ItemType = Literal["artists", "tracks"]
TimeRange = Literal["short_term", "medium_term", "long_term"]

VALID_ITEM_TYPES = {"artists", "tracks"}
VALID_TIME_RANGES = {"short_term", "medium_term", "long_term"}
GERMANY_TIMEZONE = ZoneInfo("Europe/Berlin")


class UsersAPI:
    """High-level access to Spotify endpoints for the current user.

    These methods describe endpoint paths and validate their parameters. Actual
    authentication and HTTP handling are delegated to ``SpotifyClient``.
    """

    def __init__(self, client: SpotifyClient) -> None:
        """Create the user API using a shared authenticated client."""
        self._client = client

    def profile(self) -> dict[str, Any]:
        """Return profile information for the authorized Spotify account.

        Basic profile fields are returned without additional scopes. Some fields
        require ``user-read-private`` or ``user-read-email``.
        """
        return self._get_object("/me")

    def top_items(
        self,
        item_type: ItemType,
        *,
        time_range: TimeRange = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return the user's top artists or tracks.

        ``short_term`` is approximately four weeks, ``medium_term`` six months,
        and ``long_term`` about one year. This endpoint requires the
        ``user-top-read`` scope.
        """
        if item_type not in VALID_ITEM_TYPES:
            raise ValueError("item_type must be 'artists' or 'tracks'.")
        if time_range not in VALID_TIME_RANGES:
            raise ValueError("time_range must be 'short_term', 'medium_term', or 'long_term'.")
        self._validate_limit(limit)
        if offset < 0:
            raise ValueError("offset must be zero or greater.")

        return self._get_object(
            f"/me/top/{item_type}",
            params={"time_range": time_range, "limit": limit, "offset": offset},
        )

    def top_tracks(
        self,
        *,
        time_range: TimeRange = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return the user's top tracks; shorthand for ``top_items('tracks')``."""
        return self.top_items("tracks", time_range=time_range, limit=limit, offset=offset)

    def top_artists(
        self,
        *,
        time_range: TimeRange = "medium_term",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return the user's top artists; shorthand for ``top_items('artists')``."""
        return self.top_items("artists", time_range=time_range, limit=limit, offset=offset)

    def recently_played(
        self,
        *,
        limit: int = 20,
        after: datetime | None = None,
        before: datetime | None = None,
    ) -> dict[str, Any]:
        """Return the user's recently played tracks.

        ``after`` and ``before`` cannot be supplied together. Naive datetimes
        default to Germany's ``Europe/Berlin`` timezone; aware datetimes retain
        their timezone. They are converted to the Unix timestamp in milliseconds
        expected by Spotify. The endpoint requires the
        ``user-read-recently-played`` scope.
        """
        self._validate_limit(limit)
        if after is not None and before is not None:
            raise ValueError("after and before cannot be used together.")

        return self._get_object(
            "/me/player/recently-played",
            params={
                "limit": limit,
                "after": self._to_unix_milliseconds(after, "after"),
                "before": self._to_unix_milliseconds(before, "before"),
            },
        )

    def _get_object(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Make a GET request and ensure the endpoint returned a JSON object."""
        result = self._client.get(path, **kwargs)
        if not isinstance(result, dict):
            raise TypeError(f"Spotify returned an unexpected response for {path}.")
        return result

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Validate the 1–50 page-size range shared by these endpoints."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50.")

    @staticmethod
    def _to_unix_milliseconds(value: datetime | None, parameter: str) -> int | None:
        """Convert a datetime to Unix milliseconds, defaulting to German time."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=GERMANY_TIMEZONE)

        timestamp = int(value.timestamp() * 1000)
        if timestamp < 0:
            raise ValueError(f"{parameter} cannot be before the Unix epoch.")
        return timestamp
