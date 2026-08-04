from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from spotify_lab.spotify.client import SpotifyClient
from spotify_lab.spotify.users import UsersAPI


def test_top_tracks_calls_user_endpoint_with_parameters():
    client = MagicMock(spec=SpotifyClient)
    client.get.return_value = {"items": [{"name": "A track"}]}
    users = UsersAPI(client)

    result = users.top_tracks(time_range="short_term", limit=10)

    assert result["items"][0]["name"] == "A track"
    client.get.assert_called_once_with(
        "/me/top/tracks",
        params={"time_range": "short_term", "limit": 10, "offset": 0},
    )


def test_recently_played_omits_unused_cursor_in_client():
    client = MagicMock(spec=SpotifyClient)
    client.get.return_value = {"items": []}
    users = UsersAPI(client)

    users.recently_played(
        limit=5,
        after=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
    )

    client.get.assert_called_once_with(
        "/me/player/recently-played",
        params={"limit": 5, "after": 1_700_000_000_000, "before": None},
    )


@pytest.mark.parametrize("limit", [0, 51])
def test_user_endpoint_rejects_invalid_limit(limit):
    users = UsersAPI(MagicMock(spec=SpotifyClient))

    with pytest.raises(ValueError, match="between 1 and 50"):
        users.top_artists(limit=limit)


def test_recently_played_rejects_two_cursors():
    users = UsersAPI(MagicMock(spec=SpotifyClient))
    after = datetime(2025, 1, 1, tzinfo=UTC)
    before = datetime(2025, 1, 2, tzinfo=UTC)

    with pytest.raises(ValueError, match="cannot be used together"):
        users.recently_played(after=after, before=before)


def test_recently_played_defaults_naive_datetime_to_germany():
    client = MagicMock(spec=SpotifyClient)
    client.get.return_value = {"items": []}
    users = UsersAPI(client)
    naive_german_time = datetime(2025, 1, 1, 12)

    users.recently_played(after=naive_german_time)

    expected = int(naive_german_time.replace(tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)
    client.get.assert_called_once_with(
        "/me/player/recently-played",
        params={"limit": 20, "after": expected, "before": None},
    )
