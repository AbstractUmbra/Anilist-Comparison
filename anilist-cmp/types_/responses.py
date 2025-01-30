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


class AnilistResponse(TypedDict):
    data: dict[str, MediaListCollection]


class AnilistErrorLocation(TypedDict):
    line: int
    column: int


class AnilistError(TypedDict):
    message: str
    status: int
    locations: list[AnilistErrorLocation]


class UserEntryError(TypedDict):
    user1: None
    user2: None


class AnilistErrorResponse(TypedDict):
    errors: list[AnilistError]
    data: UserEntryError
