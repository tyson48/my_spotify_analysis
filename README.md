# my_spotify_analysis

Analysis of my Spotify data.

## Spotify authorization

This project uses Spotify's **Authorization Code with PKCE** flow. It can access
data belonging to your Spotify account without putting a client secret in the
application.

### 1. Create and configure a Spotify app

1. Open the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard),
   sign in, and create an app.
2. Open the app's settings and add this Redirect URI exactly:

   ```text
   http://127.0.0.1:8888/callback
   ```

3. Save the settings and copy the app's **Client ID**. A client secret is not
   needed for PKCE.

Spotify does not accept `http://localhost` as a redirect URI. The loopback IP,
port, path, and trailing slash must match the configured value.

### 2. Configure the local environment

Create your private local configuration from the provided template:

```bash
cp .env.example .env
```

Then replace `your_client_id_here` inside `.env` with the Client ID copied from
the Spotify dashboard. The application loads `.env` automatically and Git
ignores it. Keep `.env.example` unchanged so it remains a safe configuration
template. Values explicitly exported in your shell take precedence over `.env`.

By default, the app requests only these analysis-related scopes:

```text
user-top-read user-read-recently-played
```

Override `SPOTIFY_SCOPES` with a space-separated value if another API endpoint
requires more permissions. Spotify will ask you to consent again when scopes
change.

### 3. Authorize the account

From the repository root, run:

```bash
PYTHONPATH=src poetry run python -m spotify_lab.auth
```

The command opens Spotify in your browser and starts a temporary callback server
on `127.0.0.1:8888`. After you approve access, it exchanges the one-time code for
tokens and saves them to `.spotify_tokens.json`. This file contains credentials,
is permission-restricted, and is excluded from Git.

Subsequent calls can obtain a valid access token (and refresh it automatically):

```python
from spotify_lab.auth import SpotifyOAuth
from spotify_lab.config import SpotifyConfig

access_token = SpotifyOAuth(SpotifyConfig.from_env()).get_access_token()
```

Pass it in API requests as `Authorization: Bearer <access_token>`. To force a new
consent flow, call `get_access_token(force_login=True)`. To disconnect locally,
delete `.spotify_tokens.json`; you can also revoke the app in your Spotify
account settings.

## Calling user endpoints

``SpotifyClient`` contains the shared authenticated HTTP behavior, while
``UsersAPI`` contains endpoints concerning the authorized account:

```python
from datetime import UTC, datetime, timedelta

from spotify_lab.auth import SpotifyOAuth
from spotify_lab.config import SpotifyConfig
from spotify_lab.spotify import SpotifyClient, UsersAPI

oauth = SpotifyOAuth(SpotifyConfig.from_env())
client = SpotifyClient(oauth)
users = UsersAPI(client)

profile = users.profile()
top_tracks = users.top_tracks(time_range="medium_term", limit=10)
recent = users.recently_played(
    limit=10,
    after=datetime.now(UTC) - timedelta(days=7),
)

for track in top_tracks["items"]:
    print(track["name"])
```

The `after` and `before` values for `recently_played()` accept Python datetimes.
If a datetime has no timezone, it is interpreted as German local time using
`Europe/Berlin` (including the appropriate CET or CEST offset).

The configured default scopes support top items and recently played tracks.
Add `user-read-private` or `user-read-email` only if you need the corresponding
restricted profile fields, then run authorization again with `force_login=True`.
