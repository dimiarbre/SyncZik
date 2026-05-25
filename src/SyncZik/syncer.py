from __future__ import annotations

from datetime import datetime
from typing import Optional

from utils import ServiceName


class Artist:
    def __init__(self, name: str, id: str):
        self.name = name
        self.id = id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Artist):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self) -> dict:
        return {"name": self.name, "id": self.id}

    @classmethod
    def from_dict(cls, d: dict) -> Artist:
        return cls(name=d["name"], id=d["id"])


class Song:
    def __init__(self, name: str, artists: list[Artist], uri: str, id: str):
        self.name = name
        self.artists = artists
        self.uri = uri
        self.id = id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Song):
            return NotImplemented
        return self.name == other.name and self.id == other.id and self.uri == other.uri

    def __hash__(self) -> int:
        return hash(self.id)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "artists": [a.to_dict() for a in self.artists],
            "uri": self.uri,
            "id": self.id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Song:
        return cls(
            name=d["name"],
            artists=[Artist.from_dict(a) for a in d["artists"]],
            uri=d["uri"],
            id=d["id"],
        )


class Playlist:
    def __init__(
        self,
        service: ServiceName,
        service_id: str,
        name: str,
        owner: str,
        parent_id: Optional[str] = None,
        parent_service: Optional[ServiceName] = None,
        last_synced: Optional[datetime] = None,
    ):
        self.service = service
        self.service_id = service_id
        self.name = name
        self.owner = owner
        self.parent_id = parent_id
        self.parent_service = parent_service
        self.last_synced = last_synced
        self.songs: list[Song] = []

    def add_song(self, song: Song, allow_duplicate: bool = False) -> bool:
        if not allow_duplicate and song in self:
            return False
        self.songs.append(song)
        return True

    def remove_song(self, song: Song) -> bool:
        for i, s in enumerate(self.songs):
            if s == song:
                self.songs.pop(i)
                return True
        return False

    def __contains__(self, song: Song) -> bool:
        return any(s == song for s in self.songs)

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "service_id": self.service_id,
            "name": self.name,
            "owner": self.owner,
            "parent_id": self.parent_id,
            "parent_service": self.parent_service,
            "last_synced": self.last_synced.isoformat() if self.last_synced else None,
            "songs": [s.to_dict() for s in self.songs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Playlist:
        last_synced = datetime.fromisoformat(d["last_synced"]) if d.get("last_synced") else None
        playlist = cls(
            service=d["service"],
            service_id=d["service_id"],
            name=d["name"],
            owner=d["owner"],
            parent_id=d.get("parent_id"),
            parent_service=d.get("parent_service"),
            last_synced=last_synced,
        )
        playlist.songs = [Song.from_dict(s) for s in d.get("songs", [])]
        return playlist
