import os
from typing import Literal

from dotenv import load_dotenv

# Define common types.
ServiceName = Literal["spotify", "deezer"]

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
DEEZER_ACCESS_TOKEN = os.getenv("DEEZER_ACCESS_TOKEN")
