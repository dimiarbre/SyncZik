from utils import ServiceName


class Song:
    def __init__(
        self,
        name,
        artists,
        uri,
        id,
    ):
        self.name = name
        self.artists = artists
        self.uri = uri
        self.id = id

    def __eq__(self, song):
        if not isinstance(song, Song):
            raise NotImplementedError(f"Cannot compare Song and {type(song)}")
        return self.name == song.name and self.id == song.id and self.uri == song.uri


class Artist:
    def __init__(self, name, id):
        self.name = name
        self.id = id


class Playslist:
    def __init__(self, playlist_id: str, playlist_name: str, playlist_owner: str):
        self.playlist_id = playlist_id
        self.playlist_name = playlist_name
        self.owner = playlist_owner
        self.songs: list[Song] = []

    def add_song(self, song, allow_duplicate=False) -> bool:
        if not allow_duplicate and song in self:
            return False
        self.songs.append(song)
        return True

    def __contains__(self, song: Song):
        for s in self.songs:
            if song.equals(s):
                return True
        return False
