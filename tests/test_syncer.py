from SyncZik.syncer import Artist, Playlist, Song


def make_song(name="Track", id="id1", uri="spotify:track:id1") -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=uri, id=id)


class TestSong:
    def test_equality_by_id_and_uri(self):
        s1 = make_song()
        s2 = make_song()
        assert s1 == s2

    def test_inequality_different_id(self):
        s1 = make_song(id="id1", uri="spotify:track:id1")
        s2 = make_song(id="id2", uri="spotify:track:id2")
        assert s1 != s2

    def test_roundtrip(self):
        s = make_song()
        assert Song.from_dict(s.to_dict()) == s

    def test_hash_usable_in_set(self):
        s1 = make_song()
        s2 = make_song()
        assert len({s1, s2}) == 1


class TestSongMetadata:
    def test_new_fields_default_to_none(self):
        s = make_song()
        assert s.album is None
        assert s.duration_ms is None
        assert s.isrc is None
        assert s.added_at is None

    def test_roundtrip_with_metadata(self):
        s = Song(
            name="A",
            artists=[Artist("Art", "a1")],
            uri="u",
            id="i",
            album="Album",
            duration_ms=123456,
            isrc="US123",
            added_at="2024-01-01T00:00:00Z",
        )
        loaded = Song.from_dict(s.to_dict())
        assert loaded.album == "Album"
        assert loaded.duration_ms == 123456
        assert loaded.isrc == "US123"
        assert loaded.added_at == "2024-01-01T00:00:00Z"

    def test_from_dict_without_metadata_keys_defaults_to_none(self):
        # Simulates loading a state/snapshot file saved before these fields existed.
        old_dict = {"name": "A", "artists": [{"name": "Art", "id": "a1"}], "uri": "u", "id": "i"}
        loaded = Song.from_dict(old_dict)
        assert loaded.album is None
        assert loaded.duration_ms is None
        assert loaded.isrc is None
        assert loaded.added_at is None

    def test_metadata_does_not_affect_equality(self):
        a = make_song()
        b = Song(name=a.name, artists=a.artists, uri=a.uri, id=a.id, isrc="different")
        assert a == b


class TestArtist:
    def test_equality_by_id(self):
        assert Artist("Daft Punk", "dp") == Artist("Daft Punk", "dp")

    def test_roundtrip(self):
        a = Artist("Daft Punk", "dp")
        assert Artist.from_dict(a.to_dict()).id == "dp"


class TestPlaylist:
    def test_add_song_no_duplicate(self):
        p = Playlist(service="spotify", service_id="p1", name="P", owner="me")
        s = make_song()
        assert p.add_song(s) is True
        assert p.add_song(s) is False
        assert len(p.songs) == 1

    def test_add_song_allow_duplicate(self):
        p = Playlist(service="spotify", service_id="p1", name="P", owner="me")
        s = make_song()
        p.add_song(s)
        assert p.add_song(s, allow_duplicate=True) is True
        assert len(p.songs) == 2

    def test_contains(self):
        p = Playlist(service="spotify", service_id="p1", name="P", owner="me")
        s = make_song()
        p.add_song(s)
        assert s in p
        other = make_song(id="x", uri="spotify:track:x")
        assert other not in p

    def test_remove_song(self):
        p = Playlist(service="spotify", service_id="p1", name="P", owner="me")
        s = make_song()
        p.add_song(s)
        assert p.remove_song(s) is True
        assert s not in p
        assert p.remove_song(s) is False

    def test_roundtrip_with_songs(self):
        p = Playlist(
            service="spotify",
            service_id="p1",
            name="P",
            owner="me",
            parent_id="source1",
            parent_service="spotify",
        )
        p.add_song(make_song("A", "id_a", "spotify:track:id_a"))
        p.add_song(make_song("B", "id_b", "spotify:track:id_b"))
        p2 = Playlist.from_dict(p.to_dict())
        assert p2.name == "P"
        assert p2.parent_id == "source1"
        assert len(p2.songs) == 2
        assert p2.songs[0].name == "A"
