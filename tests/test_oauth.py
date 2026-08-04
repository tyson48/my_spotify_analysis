import base64
import hashlib
import json
import time
import urllib.parse
from unittest.mock import MagicMock, patch

from spotify_lab.auth.oauth import SpotifyOAuth, Token
from spotify_lab.config import SpotifyConfig


def test_valid_cached_token_is_reused(tmp_path):
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "cached-access-token",
                "token_type": "Bearer",
                "scope": "user-top-read",
                "expires_at": int(time.time()) + 3600,
                "refresh_token": "refresh-token",
            }
        )
    )
    oauth = SpotifyOAuth(SpotifyConfig(client_id="client-id", token_path=token_path))

    assert oauth.get_access_token() == "cached-access-token"


def test_expired_token_is_refreshed_and_saved(tmp_path):
    token_path = tmp_path / "tokens.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "expired",
                "token_type": "Bearer",
                "scope": "user-top-read",
                "expires_at": 0,
                "refresh_token": "old-refresh-token",
            }
        )
    )
    oauth = SpotifyOAuth(SpotifyConfig(client_id="client-id", token_path=token_path))

    with patch.object(
        oauth,
        "_post_token",
        return_value={
            "access_token": "fresh-access-token",
            "token_type": "Bearer",
            "scope": "user-top-read",
            "expires_in": 3600,
        },
    ) as post_token:
        assert oauth.get_access_token() == "fresh-access-token"

    assert post_token.call_args.args[0] == {
        "client_id": "client-id",
        "grant_type": "refresh_token",
        "refresh_token": "old-refresh-token",
    }
    assert json.loads(token_path.read_text())["refresh_token"] == "old-refresh-token"


def test_authorization_url_uses_pkce_and_state(tmp_path):
    config = SpotifyConfig(client_id="client-id", token_path=tmp_path / "tokens.json")
    oauth = SpotifyOAuth(config)
    captured: dict[str, str] = {}

    def capture_callback(path: str, port: int, state: str) -> str:
        captured.update(path=path, port=str(port), state=state)
        return "authorization-code"

    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "access_token": "access-token",
            "token_type": "Bearer",
            "scope": "user-top-read",
            "expires_in": 3600,
            "refresh_token": "refresh-token",
        }
    ).encode()

    with (
        patch("spotify_lab.auth.oauth.webbrowser.open") as browser_open,
        patch.object(oauth, "_wait_for_callback", side_effect=capture_callback),
        patch("spotify_lab.auth.oauth.urllib.request.urlopen", return_value=response) as urlopen,
    ):
        token = oauth._authorize()

    authorize_url = browser_open.call_args.args[0]
    params = urllib.parse.parse_qs(urllib.parse.urlparse(authorize_url).query)
    form = urllib.parse.parse_qs(urlopen.call_args.args[0].data.decode())
    verifier = form["code_verifier"][0]
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )

    assert token.access_token == "access-token"
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [expected_challenge]
    assert params["state"] == [captured["state"]]
    assert form["client_id"] == ["client-id"]
    assert form["code"] == ["authorization-code"]
    assert form["redirect_uri"] == [config.redirect_uri]


def test_token_expiry_has_safety_margin():
    token = Token("access", "Bearer", "", int(time.time()) + 30, "refresh")

    assert token.is_expired


def test_config_loads_dotenv_before_reading_environment(monkeypatch):
    def provide_dotenv_values() -> None:
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "client-from-dotenv")

    with patch("spotify_lab.config.load_dotenv", side_effect=provide_dotenv_values) as loader:
        config = SpotifyConfig.from_env()

    loader.assert_called_once_with()
    assert config.client_id == "client-from-dotenv"
