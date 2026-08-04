"""Authenticated clients for the Spotify Web API."""

from spotify_lab.spotify.client import SpotifyAPIError, SpotifyClient
from spotify_lab.spotify.users import UsersAPI

__all__ = ["SpotifyAPIError", "SpotifyClient", "UsersAPI"]
