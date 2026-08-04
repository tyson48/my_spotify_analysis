"""Spotify Authorization Code with PKCE flow for a local Python application."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from spotify_lab.config import SpotifyConfig

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
EXPIRY_MARGIN_SECONDS = 60


class SpotifyAuthError(RuntimeError):
    """Raised when Spotify authorization or token handling fails."""


@dataclass(frozen=True)
class Token:
    """The credentials and metadata returned by Spotify's token endpoint.

    ``access_token`` is the short-lived credential sent with Web API requests.
    ``refresh_token`` is the longer-lived credential used to obtain another
    access token without asking the user to sign in again. ``expires_at`` is an
    absolute Unix timestamp calculated from Spotify's relative ``expires_in``
    response value.
    """

    access_token: str
    token_type: str
    scope: str
    expires_at: int
    refresh_token: str | None = None

    @property
    def is_expired(self) -> bool:
        """Return whether the access token is expired or close to expiring.

        A small safety margin prevents callers from starting an API request with
        a token that expires while that request is in progress.
        """
        return time.time() >= self.expires_at - EXPIRY_MARGIN_SECONDS

    @classmethod
    def from_response(
        cls, payload: dict[str, Any], previous_refresh_token: str | None = None
    ) -> Token:
        """Build a token from Spotify's authorization or refresh response.

        Spotify may omit ``refresh_token`` when refreshing an access token. In
        that case, ``previous_refresh_token`` preserves the still-valid token we
        already have.

        Raises:
            SpotifyAuthError: If required response fields are absent or invalid.
        """
        try:
            return cls(
                access_token=str(payload["access_token"]),
                token_type=str(payload.get("token_type", "Bearer")),
                scope=str(payload.get("scope", "")),
                expires_at=int(time.time()) + int(payload["expires_in"]),
                refresh_token=payload.get("refresh_token") or previous_refresh_token,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SpotifyAuthError("Spotify returned an invalid token response.") from error

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Token:
        """Reconstruct a token from the normalized on-disk cache format.

        Raises:
            SpotifyAuthError: If the cache does not contain valid token data.
        """
        try:
            return cls(
                access_token=str(payload["access_token"]),
                token_type=str(payload["token_type"]),
                scope=str(payload.get("scope", "")),
                expires_at=int(payload["expires_at"]),
                refresh_token=payload.get("refresh_token"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SpotifyAuthError("The saved Spotify token file is invalid.") from error

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert the token to the JSON-serializable cache representation."""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "scope": self.scope,
            "expires_at": self.expires_at,
            "refresh_token": self.refresh_token,
        }


class SpotifyOAuth:
    """Authorize a Spotify user and maintain a usable access token.

    This class implements OAuth's Authorization Code flow with PKCE for a local
    application. PKCE proves that the process exchanging the authorization code
    is the same process that started authorization, so this application does not
    need to store a Spotify client secret.

    The high-level lifecycle is:

    1. Reuse a cached access token if it is still valid.
    2. Otherwise use its refresh token to obtain a new access token.
    3. If no usable refresh token exists, ask the user to authorize in a browser.
    """

    def __init__(self, config: SpotifyConfig) -> None:
        """Create an OAuth client using the supplied app and cache settings."""
        self.config = config

    def get_access_token(self, *, force_login: bool = False) -> str:
        """Return a usable access token, refreshing or authorizing as needed.

        Args:
            force_login: Ignore cached credentials and start browser authorization
                immediately. This is useful when changing Spotify accounts or
                requesting a different set of scopes.

        Returns:
            A bearer token suitable for the Web API ``Authorization`` header.

        Raises:
            SpotifyAuthError: If authorization fails or the token cache is invalid.
        """
        token = None if force_login else self._load_token()
        if token and not token.is_expired:
            return token.access_token
        if token and token.refresh_token:
            try:
                token = self._refresh(token.refresh_token)
                self._save_token(token)
                return token.access_token
            except SpotifyAuthError:
                # A revoked or expired refresh token requires fresh user consent.
                pass

        token = self._authorize()
        self._save_token(token)
        return token.access_token

    def _authorize(self) -> Token:
        """Run an interactive PKCE authorization from start to finish.

        A random verifier stays only in this Python process. Its SHA-256-derived
        challenge is sent to Spotify with a random ``state`` value. After the
        browser redirects to the local callback server, the one-time code is
        exchanged together with the original verifier for access and refresh
        tokens. The state value protects the callback against request forgery.
        """
        redirect = urllib.parse.urlparse(self.config.redirect_uri)
        if redirect.scheme != "http" or redirect.hostname != "127.0.0.1":
            raise SpotifyAuthError(
                "Local authorization requires a redirect URI such as "
                "http://127.0.0.1:8888/callback."
            )
        if redirect.port is None:
            raise SpotifyAuthError("SPOTIFY_REDIRECT_URI must include a port.")

        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        state = secrets.token_urlsafe(32)
        query = urllib.parse.urlencode(
            {
                "client_id": self.config.client_id,
                "response_type": "code",
                "redirect_uri": self.config.redirect_uri,
                "scope": " ".join(self.config.scopes),
                "state": state,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
        )
        authorization_url = f"{AUTHORIZE_URL}?{query}"

        print("Opening Spotify authorization in your browser...")
        print(f"If it does not open, visit:\n{authorization_url}\n")
        webbrowser.open(authorization_url)
        code = self._wait_for_callback(redirect.path or "/", redirect.port, state)

        return Token.from_response(
            self._post_token(
                {
                    "client_id": self.config.client_id,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.config.redirect_uri,
                    "code_verifier": verifier,
                }
            )
        )

    def _wait_for_callback(self, path: str, port: int, expected_state: str) -> str:
        """Receive and validate Spotify's single redirect to the loopback server.

        The server handles one request and then shuts down. It verifies both the
        configured callback path and the random OAuth state before returning the
        authorization code. Waiting stops after three minutes.

        Args:
            path: Callback URL path, for example ``/callback``.
            port: Loopback TCP port on which to receive Spotify's redirect.
            expected_state: Random state created for this authorization attempt.

        Returns:
            Spotify's short-lived, single-use authorization code.

        Raises:
            SpotifyAuthError: If consent is denied, validation fails, or the wait
                times out.
        """
        result: dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(handler_self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(handler_self.path)
                if parsed.path != path:
                    handler_self.send_error(404)
                    return

                params = urllib.parse.parse_qs(parsed.query)
                if params.get("state", [None])[0] != expected_state:
                    result["error"] = "OAuth state did not match; authorization was rejected."
                elif "error" in params:
                    result["error"] = f"Spotify authorization failed: {params['error'][0]}"
                elif "code" not in params:
                    result["error"] = "Spotify callback did not include an authorization code."
                else:
                    result["code"] = params["code"][0]

                ok = "code" in result
                body = (
                    "Spotify authorization complete. You can close this tab."
                    if ok
                    else result["error"]
                ).encode()
                handler_self.send_response(200 if ok else 400)
                handler_self.send_header("Content-Type", "text/plain; charset=utf-8")
                handler_self.send_header("Content-Length", str(len(body)))
                handler_self.end_headers()
                handler_self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", port), CallbackHandler)
        server.timeout = 180
        server.handle_request()
        server.server_close()

        if "code" not in result:
            raise SpotifyAuthError(
                result.get("error", "Timed out waiting for Spotify authorization.")
            )
        return result["code"]

    def _refresh(self, refresh_token: str) -> Token:
        """Exchange a refresh token for a new access token.

        Spotify does not always rotate the refresh token. ``Token.from_response``
        therefore carries the current one forward when none is returned.
        """
        payload = self._post_token(
            {
                "client_id": self.config.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
        return Token.from_response(payload, previous_refresh_token=refresh_token)

    def _post_token(self, form: dict[str, str]) -> dict[str, Any]:
        """Send a form-encoded request to Spotify's shared token endpoint.

        Both the initial authorization-code exchange and later refreshes use this
        endpoint with different ``grant_type`` values.

        Raises:
            SpotifyAuthError: If Spotify rejects the request, cannot be reached,
                or returns an invalid response.
        """
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(form).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                details = json.loads(error.read()).get("error_description", error.reason)
            except (json.JSONDecodeError, AttributeError):
                details = error.reason
            raise SpotifyAuthError(f"Spotify token request failed: {details}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise SpotifyAuthError(f"Could not reach Spotify: {error}") from error
        except json.JSONDecodeError as error:
            raise SpotifyAuthError("Spotify returned a non-JSON token response.") from error

        if not isinstance(payload, dict):
            raise SpotifyAuthError("Spotify returned an invalid token response.")
        return payload

    def _load_token(self) -> Token | None:
        """Load cached credentials, returning ``None`` when no cache exists.

        Raises:
            SpotifyAuthError: If a cache exists but cannot be read or validated.
        """
        try:
            payload = json.loads(self.config.token_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise SpotifyAuthError(
                f"Could not read token cache {self.config.token_path}."
            ) from error
        if not isinstance(payload, dict):
            raise SpotifyAuthError("The saved Spotify token file is invalid.")
        return Token.from_dict(payload)

    def _save_token(self, token: Token) -> None:
        """Persist credentials and limit the cache file to owner access.

        The cache includes a refresh token and must be treated like a password.
        File mode ``0600`` prevents other local users from reading or modifying it.
        """
        path: Path = self.config.token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(token.to_dict(), indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)


def main() -> None:
    """Authorize from the CLI and report where credentials were cached."""
    try:
        config = SpotifyConfig.from_env()
        oauth = SpotifyOAuth(config)
        oauth.get_access_token()
    except (SpotifyAuthError, ValueError) as error:
        raise SystemExit(f"Authorization failed: {error}") from error
    print(f"Spotify authorization succeeded. Token saved to {config.token_path}.")


if __name__ == "__main__":
    main()
