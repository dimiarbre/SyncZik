"""Cross-platform playlist export with conflict detection and resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .providers.base import ServiceProvider
from .syncer import Song


class MatchKind(Enum):
    EXACT = "exact"  # title + first artist match after normalization
    AMBIGUOUS = "ambiguous"  # candidates found but no definitive match
    NOT_FOUND = "not_found"  # target platform returned nothing


@dataclass
class SongConflict:
    source: Song
    kind: MatchKind
    candidates: list[Song] = field(default_factory=list)


@dataclass
class ExportPlan:
    auto_resolved: list[tuple[Song, Song]] = field(default_factory=list)  # (source, target)
    conflicts: list[SongConflict] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not self.conflicts

    def total(self) -> int:
        return len(self.auto_resolved) + len(self.conflicts)


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation noise, remove featuring suffixes."""
    text = text.lower().strip()
    text = re.sub(r"\s*[\(\[](feat|ft|with|prod)\.?[^\)\]]*[\)\]]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(feat|ft)\.?\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()


def _is_exact_match(source: Song, candidate: Song) -> bool:
    """True when title and first artist both match after normalization."""
    if not source.artists or not candidate.artists:
        return False
    return _normalize(source.name) == _normalize(candidate.name) and _normalize(
        source.artists[0].name
    ) == _normalize(candidate.artists[0].name)


def _isrc_match(source: Song, candidate: Song) -> bool:
    """True when both songs carry the same ISRC — the most reliable way to
    identify the same recording across services, independent of how each
    platform formats the title/artist."""
    return bool(source.isrc) and bool(candidate.isrc) and source.isrc == candidate.isrc


def _duration_diff_ms(source: Song, candidate: Song) -> int | None:
    if source.duration_ms is None or candidate.duration_ms is None:
        return None
    return abs(source.duration_ms - candidate.duration_ms)


def _best_exact_match(source: Song, candidates: list[Song]) -> Song | None:
    """Among normalized title+artist matches, prefer the closest duration when
    more than one candidate ties — guards against a remix/live version
    outranking the studio cut just because it was returned first."""
    exact = [c for c in candidates if _is_exact_match(source, c)]
    if not exact:
        return None
    if len(exact) == 1:
        return exact[0]
    diffs = [(c, d) for c in exact if (d := _duration_diff_ms(source, c)) is not None]
    if diffs:
        return min(diffs, key=lambda pair: pair[1])[0]
    return exact[0]


def plan_export(
    source_songs: list[Song],
    target_provider: ServiceProvider,
    search_limit: int = 5,
) -> ExportPlan:
    """Classify each source song as auto-resolved or conflicted on the target platform.

    A shared ISRC is the strongest signal and is checked first. Otherwise, an
    exact match (normalized title + first artist) is auto-resolved, breaking
    ties between multiple exact matches by closest duration. Partial matches
    are flagged as AMBIGUOUS so the user can pick a candidate. Zero results
    are flagged as NOT_FOUND so the user can search manually or skip.
    """
    plan = ExportPlan()

    for song in source_songs:
        query = f"{song.name} {song.artists[0].name}" if song.artists else song.name
        candidates = target_provider.search_tracks(query, limit=search_limit)

        isrc_match = next((c for c in candidates if _isrc_match(song, c)), None)
        best = isrc_match or _best_exact_match(song, candidates)
        if best:
            plan.auto_resolved.append((song, best))
        elif candidates:
            plan.conflicts.append(SongConflict(source=song, kind=MatchKind.AMBIGUOUS, candidates=candidates))
        else:
            plan.conflicts.append(SongConflict(source=song, kind=MatchKind.NOT_FOUND))

    return plan


def execute_export(
    target_provider: ServiceProvider,
    user_id: str,
    playlist_name: str,
    songs: list[Song],
    description: str = "",
) -> str:
    """Create the exported playlist on the target platform and populate it.

    Returns the new playlist ID.
    """
    playlist_id = target_provider.create_playlist(user_id, playlist_name, description)
    if songs:
        target_provider.add_songs(playlist_id, songs)
    return playlist_id
