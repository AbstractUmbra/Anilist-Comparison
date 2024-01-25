from __future__ import annotations

from typing import TypedDict


class LocalizedTitle(TypedDict):
    romaji: str | None
    english: str | None
    native: str | None


class InnerMediaEntry(TypedDict):
    id: int
    title: LocalizedTitle
    siteUrl: str


class MediaEntry(TypedDict):
    media: InnerMediaEntry


class MediaListEntry(TypedDict):
    entries: list[MediaEntry]


class MediaListCollection(TypedDict):
    lists: list[MediaListEntry]


class MediaListCollectionResponse(TypedDict):
    user1: MediaListCollection
    user2: MediaListCollection


class AnilistResponse(TypedDict):
    data: MediaListCollectionResponse
