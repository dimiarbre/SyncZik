from utils import ServiceName


class Song:
    def __init__(self):
        pass


class Playslist:
    def __init__(self, playlist_id, service: ServiceName):
        self.service = service
        self.playlist_id = playlist_id
        self.songs: list[Song] = []
