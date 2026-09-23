from unittest.mock import MagicMock

import pytest
from SyncZik.syncer import Artist, Song
from SyncZik.providers.base import ServiceProvider
from SyncZik.cross_platform import (
    ExportPlan,
    MatchKind,
    SongConflict,
    _best_exact_match,
    _duration_diff_ms,
    _isrc_match,
    _normalize,
    _is_exact_match,
    execute_export,
    plan_export,
)


def make_song(name="Track", artist="Artist", id="s1", uri=None, isrc=None, duration_ms=None) -> Song:
    return Song(
        name=name,
        artists=[Artist(artist, f"{artist.lower()}_id")],
        uri=uri or f"spotify:track:{id}",
        id=id,
        isrc=isrc,
        duration_ms=duration_ms,
    )


def make_provider(search_results: list[Song], new_id: str = "new_pl") -> ServiceProvider:
    provider = MagicMock(spec=ServiceProvider)
    provider.service_name = "deezer"
    provider.search_tracks.return_value = list(search_results)
    provider.create_playlist.return_value = new_id
    return provider


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNCZIK_DATA_DIR", str(tmp_path / "xdg_data"))


# ---------------------------------------------------------------------------
# _normalize()
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercases(self):
        assert _normalize("HELLO WORLD") == "hello world"

    def test_strips_whitespace(self):
        assert _normalize("  hello  ") == "hello"

    def test_removes_feat_in_parens(self):
        assert _normalize("Starboy (feat. Daft Punk)") == "starboy"

    def test_removes_feat_in_brackets(self):
        assert _normalize("Starboy [feat. Daft Punk]") == "starboy"

    def test_removes_ft_suffix(self):
        assert _normalize("Get Lucky ft. Pharrell") == "get lucky"

    def test_removes_feat_suffix_no_parens(self):
        assert _normalize("Get Lucky feat. Pharrell Williams") == "get lucky"

    def test_strips_punctuation(self):
        assert _normalize("It's Tricky") == "its tricky"

    def test_identical_after_normalize(self):
        a = _normalize("Starboy (feat. Daft Punk)")
        b = _normalize("Starboy")
        assert a == b


# ---------------------------------------------------------------------------
# _is_exact_match()
# ---------------------------------------------------------------------------

class TestIsExactMatch:
    def test_exact_title_and_artist(self):
        source = make_song("One More Time", "Daft Punk", "s1")
        candidate = make_song("One More Time", "Daft Punk", "d1")
        assert _is_exact_match(source, candidate)

    def test_feat_in_source_matches_clean_title(self):
        source = make_song("Starboy (feat. Daft Punk)", "The Weeknd", "s1")
        candidate = make_song("Starboy", "The Weeknd", "d1")
        assert _is_exact_match(source, candidate)

    def test_different_artist_no_match(self):
        source = make_song("Hotel California", "Eagles", "s1")
        candidate = make_song("Hotel California", "Not Eagles", "d1")
        assert not _is_exact_match(source, candidate)

    def test_different_title_no_match(self):
        source = make_song("Around the World", "Daft Punk", "s1")
        candidate = make_song("Around the Clock", "Daft Punk", "d1")
        assert not _is_exact_match(source, candidate)

    def test_no_artists_no_match(self):
        source = Song(name="Track", artists=[], uri="spotify:track:s1", id="s1")
        candidate = make_song("Track", "Artist", "d1")
        assert not _is_exact_match(source, candidate)

    def test_case_insensitive(self):
        source = make_song("BOHEMIAN RHAPSODY", "QUEEN", "s1")
        candidate = make_song("bohemian rhapsody", "queen", "d1")
        assert _is_exact_match(source, candidate)


# ---------------------------------------------------------------------------
# _isrc_match() / _duration_diff_ms() / _best_exact_match()
# ---------------------------------------------------------------------------

class TestIsrcMatch:
    def test_matches_on_shared_isrc(self):
        source = make_song("A", "Art", "s1", isrc="US1234567890")
        candidate = make_song("A", "Art", "d1", isrc="US1234567890")
        assert _isrc_match(source, candidate)

    def test_no_match_without_isrc_on_either_side(self):
        source = make_song("A", "Art", "s1")
        candidate = make_song("A", "Art", "d1")
        assert not _isrc_match(source, candidate)

    def test_no_match_on_different_isrc(self):
        source = make_song("A", "Art", "s1", isrc="US1")
        candidate = make_song("A", "Art", "d1", isrc="US2")
        assert not _isrc_match(source, candidate)


class TestDurationDiffMs:
    def test_returns_absolute_difference(self):
        source = make_song(duration_ms=200_000)
        candidate = make_song(duration_ms=210_000)
        assert _duration_diff_ms(source, candidate) == 10_000

    def test_none_when_either_side_missing(self):
        source = make_song(duration_ms=200_000)
        candidate = make_song()
        assert _duration_diff_ms(source, candidate) is None


class TestBestExactMatch:
    def test_single_exact_match_returned(self):
        source = make_song("Song", "Artist", "s1")
        candidate = make_song("Song", "Artist", "d1")
        assert _best_exact_match(source, [candidate]) is candidate

    def test_no_exact_match_returns_none(self):
        source = make_song("Song", "Artist", "s1")
        candidate = make_song("Different", "Artist", "d1")
        assert _best_exact_match(source, [candidate]) is None

    def test_tiebreaks_on_closest_duration(self):
        source = make_song("Song", "Artist", "s1", duration_ms=200_000)
        remix = make_song("Song", "Artist", "d1", duration_ms=340_000)
        studio = make_song("Song", "Artist", "d2", duration_ms=201_000)
        assert _best_exact_match(source, [remix, studio]) is studio

    def test_falls_back_to_first_when_no_duration_info(self):
        source = make_song("Song", "Artist", "s1")
        first = make_song("Song", "Artist", "d1")
        second = make_song("Song", "Artist", "d2")
        assert _best_exact_match(source, [first, second]) is first


# ---------------------------------------------------------------------------
# plan_export()
# ---------------------------------------------------------------------------

class TestPlanExport:
    def test_exact_match_auto_resolved(self):
        source = make_song("One More Time", "Daft Punk", "s1")
        target_song = make_song("One More Time", "Daft Punk", "d1")
        provider = make_provider([target_song])
        plan = plan_export([source], provider)
        assert len(plan.auto_resolved) == 1
        assert plan.conflicts == []
        assert plan.is_clean()

    def test_no_results_is_not_found(self):
        source = make_song("Obscure Track", "Unknown Artist", "s1")
        provider = make_provider([])
        plan = plan_export([source], provider)
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].kind == MatchKind.NOT_FOUND
        assert plan.conflicts[0].candidates == []

    def test_partial_match_is_ambiguous(self):
        source = make_song("Hotel California", "Eagles", "s1")
        wrong_match = make_song("Hotel California", "Cover Band", "d1")
        provider = make_provider([wrong_match])
        plan = plan_export([source], provider)
        assert len(plan.conflicts) == 1
        assert plan.conflicts[0].kind == MatchKind.AMBIGUOUS
        assert len(plan.conflicts[0].candidates) == 1

    def test_feat_title_resolves_to_clean_candidate(self):
        source = make_song("Starboy (feat. Daft Punk)", "The Weeknd", "s1")
        target_song = make_song("Starboy", "The Weeknd", "d1")
        provider = make_provider([target_song])
        plan = plan_export([source], provider)
        assert plan.is_clean()
        assert plan.auto_resolved[0][1].id == "d1"

    def test_mixed_songs(self):
        found = make_song("One More Time", "Daft Punk", "s1")
        missing = make_song("Exclusive Track", "Some Artist", "s2")
        ambiguous = make_song("Ambiguous", "Wrong Artist", "s3")
        provider = MagicMock(spec=ServiceProvider)
        provider.service_name = "deezer"

        def search_side_effect(query, limit=5):
            if "One More Time" in query:
                return [make_song("One More Time", "Daft Punk", "d1")]
            elif "Exclusive" in query:
                return []
            else:
                return [make_song("Ambiguous", "Slightly Different Artist", "d3")]

        provider.search_tracks.side_effect = search_side_effect
        plan = plan_export([found, missing, ambiguous], provider)
        assert len(plan.auto_resolved) == 1
        assert len(plan.conflicts) == 2
        kinds = {c.kind for c in plan.conflicts}
        assert MatchKind.NOT_FOUND in kinds
        assert MatchKind.AMBIGUOUS in kinds

    def test_empty_source_list(self):
        provider = make_provider([])
        plan = plan_export([], provider)
        assert plan.is_clean()
        assert plan.total() == 0

    def test_total_counts_all_songs(self):
        source = [make_song("A", "Art", f"s{i}") for i in range(5)]
        provider = MagicMock(spec=ServiceProvider)
        provider.service_name = "deezer"

        def search_side_effect(query, limit=5):
            name = query.split()[0]
            return [make_song(name, "Art", f"d_{name}")]

        provider.search_tracks.side_effect = search_side_effect
        plan = plan_export(source, provider)
        assert plan.total() == 5

    def test_search_called_with_name_and_first_artist(self):
        source = make_song("One More Time", "Daft Punk", "s1")
        provider = make_provider([])
        plan_export([source], provider)
        provider.search_tracks.assert_called_once()
        call_args = provider.search_tracks.call_args
        assert "One More Time" in call_args[0][0]
        assert "Daft Punk" in call_args[0][0]

    def test_isrc_match_wins_even_with_different_title(self):
        source = make_song("Original Title", "Artist", "s1", isrc="US1234567890")
        candidate = make_song("Completely Different Title", "Someone Else", "d1", isrc="US1234567890")
        provider = make_provider([candidate])
        plan = plan_export([source], provider)
        assert plan.is_clean()
        assert plan.auto_resolved[0][1].id == "d1"

    def test_duration_tiebreak_prefers_studio_over_remix(self):
        source = make_song("Song", "Artist", "s1", duration_ms=200_000)
        remix = make_song("Song", "Artist", "d1", duration_ms=340_000)
        studio = make_song("Song", "Artist", "d2", duration_ms=201_000)
        provider = make_provider([remix, studio])  # remix ranked first by search
        plan = plan_export([source], provider)
        assert plan.is_clean()
        assert plan.auto_resolved[0][1].id == "d2"


# ---------------------------------------------------------------------------
# execute_export()
# ---------------------------------------------------------------------------

class TestExecuteExport:
    def test_creates_playlist_and_adds_songs(self):
        songs = [make_song("A", "Art", "d1"), make_song("B", "Art2", "d2")]
        provider = make_provider(songs, new_id="exported123")
        playlist_id = execute_export(provider, "user", "My Export", songs)
        assert playlist_id == "exported123"
        provider.create_playlist.assert_called_once_with("user", "My Export", "")
        provider.add_songs.assert_called_once()
        added = provider.add_songs.call_args[0][1]
        assert len(added) == 2

    def test_empty_song_list_skips_add(self):
        provider = make_provider([], new_id="empty123")
        execute_export(provider, "user", "Empty Export", [])
        provider.create_playlist.assert_called_once()
        provider.add_songs.assert_not_called()

    def test_custom_description_passed_through(self):
        provider = make_provider([], new_id="pl123")
        execute_export(provider, "user", "Export", [], description="Exported from Spotify")
        provider.create_playlist.assert_called_once_with("user", "Export", "Exported from Spotify")

    def test_returns_new_playlist_id(self):
        provider = make_provider([make_song()], new_id="the_id")
        result = execute_export(provider, "user", "P", [make_song()])
        assert result == "the_id"


# ---------------------------------------------------------------------------
# ExportPlan helpers
# ---------------------------------------------------------------------------

class TestExportPlan:
    def test_is_clean_no_conflicts(self):
        plan = ExportPlan(auto_resolved=[(make_song(), make_song(id="d1"))], conflicts=[])
        assert plan.is_clean()

    def test_is_clean_with_conflicts(self):
        plan = ExportPlan(conflicts=[SongConflict(make_song(), MatchKind.NOT_FOUND)])
        assert not plan.is_clean()

    def test_total_is_sum(self):
        plan = ExportPlan(
            auto_resolved=[(make_song("A", id="a"), make_song("A", id="a2")),
                           (make_song("B", id="b"), make_song("B", id="b2"))],
            conflicts=[SongConflict(make_song("C", id="c"), MatchKind.NOT_FOUND)],
        )
        assert plan.total() == 3
