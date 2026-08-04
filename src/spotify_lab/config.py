"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_SCOPES = ("user-top-read", "user-read-recently-played")


@dataclass(frozen=True)
class SpotifyConfig:
    """Settings needed by Spotify's Authorization Code with PKCE flow.

    Attributes:
        client_id: Public identifier of the app created in Spotify's dashboard.
        redirect_uri: Local callback URL. It must exactly match a URI allowlisted
            in the app's Spotify dashboard settings.
        scopes: The user permissions requested on the consent screen.
        token_path: Local file in which access and refresh tokens are cached.

    PKCE does not require a client secret, so this configuration deliberately
    does not accept or store one.
    """

    client_id: str
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    token_path: Path = Path(".spotify_tokens.json")

    @classmethod
    def from_env(cls) -> SpotifyConfig:
        """Create configuration from ``SPOTIFY_*`` environment variables.

        Values from the nearest ``.env`` file are loaded automatically first.
        Existing shell environment variables are not overwritten, allowing a
        one-off exported value to take precedence over local file settings.

        ``SPOTIFY_CLIENT_ID`` is required. ``SPOTIFY_REDIRECT_URI``,
        ``SPOTIFY_SCOPES``, and ``SPOTIFY_TOKEN_PATH`` are optional and fall back
        to safe local-development defaults. Duplicate scopes are removed while
        retaining their original order.

        Raises:
            ValueError: If ``SPOTIFY_CLIENT_ID`` is missing or empty.
        """
        load_dotenv()

        client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        if not client_id:
            raise ValueError(
                "SPOTIFY_CLIENT_ID is not set. Copy your Client ID from the "
                "Spotify Developer Dashboard and export it in your shell."
            )

        scopes_value = os.getenv("SPOTIFY_SCOPES", " ".join(DEFAULT_SCOPES))
        scopes = tuple(dict.fromkeys(scopes_value.split()))

        return cls(
            client_id=client_id,
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            scopes=scopes,
            token_path=Path(os.getenv("SPOTIFY_TOKEN_PATH", ".spotify_tokens.json")),
        )
