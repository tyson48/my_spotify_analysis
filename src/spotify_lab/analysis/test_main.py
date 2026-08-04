from spotify_lab.auth import SpotifyOAuth
from spotify_lab.config import SpotifyConfig
from spotify_lab.spotify import SpotifyClient, UsersAPI

oauth = SpotifyOAuth(SpotifyConfig.from_env())
client = SpotifyClient(oauth)
users = UsersAPI(client)

top_tracks = users.top_tracks(time_range="short_term", limit=1)

print(top_tracks)
