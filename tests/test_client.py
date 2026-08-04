import json
import urllib.error
import urllib.parse
from email.message import Message
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from spotify_lab.spotify.client import SpotifyAPIError, SpotifyClient


def test_get_adds_token_and_encodes_query_parameters():
    token_provider = MagicMock()
    token_provider.get_access_token.return_value = "access-token"
    client = SpotifyClient(token_provider)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"items": []}).encode()

    with patch("spotify_lab.spotify.client.urllib.request.urlopen", return_value=response) as call:
        result = client.get("/me/top/tracks", params={"limit": 10, "after": None})

    request = call.call_args.args[0]
    assert result == {"items": []}
    assert request.full_url == "https://api.spotify.com/v1/me/top/tracks?limit=10"
    assert request.get_header("Authorization") == "Bearer access-token"
    token_provider.get_access_token.assert_called_once_with()


def test_api_error_exposes_status_message_and_retry_after():
    token_provider = MagicMock()
    token_provider.get_access_token.return_value = "access-token"
    client = SpotifyClient(token_provider)
    headers = Message()
    headers["Retry-After"] = "5"
    error = urllib.error.HTTPError(
        "https://api.spotify.com/v1/me",
        429,
        "Too Many Requests",
        headers,
        BytesIO(b'{"error":{"status":429,"message":"Rate limit exceeded"}}'),
    )

    with (
        patch("spotify_lab.spotify.client.urllib.request.urlopen", side_effect=error),
        pytest.raises(SpotifyAPIError) as raised,
    ):
        client.get("/me")

    assert str(raised.value) == "Rate limit exceeded"
    assert raised.value.status == 429
    assert raised.value.retry_after == 5


def test_client_rejects_absolute_urls():
    client = SpotifyClient(MagicMock())

    with pytest.raises(ValueError, match="relative"):
        client.get("https://example.com/steal-token")
