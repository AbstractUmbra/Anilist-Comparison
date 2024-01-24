from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from .types_.responses import AnilistResponse, InnerMediaEntry, MediaEntry

app = FastAPI(debug=False, title="Welcome!", version="0.0.1", openapi_url=None, redoc_url=None, docs_url=None)

QUERY = """
query ($username: String) {
    MediaListCollection(userName: $username, status: PLANNING, type: ANIME) {
        lists {
            entries {
                media {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    siteUrl
                }
            }
        }
    }
}
"""

TABLE = """
<table>
<thead>
<tr>
<th>Media ID</th>
<th>Romaji</th>
<th>English</th>
<th>Japanese</th>
<th>URL</th>
</tr>
</thead>
<tbody>
{body}
</tbody>
</table>
"""

ROW = """
<tr>
<td>{id}</td>
<td>{title[romaji]}</td>
<td>{title[english]}</td>
<td>{title[native]}</td>
<td><a href="{siteUrl}">Anilist</a></td>
</tr>
"""


def format_entries_as_table(entries: dict[int, InnerMediaEntry]) -> str:
    rows = [ROW.format_map(entry) for entry in entries.values()]
    return TABLE.format(body="\n".join(rows))


async def _query(session: aiohttp.ClientSession, json_data: dict[str, Any]) -> AnilistResponse:
    resp = await session.post("https://graphql.anilist.co", json=json_data)
    return await resp.json()


async def _fetch_user_entries(*usernames: str) -> list[AnilistResponse]:
    ret: list[AnilistResponse] = []
    async with aiohttp.ClientSession() as session, asyncio.TaskGroup() as group:
        for username in usernames:
            resp = await group.create_task(_query(session, {"query": QUERY, "variables": {"username": username}}))
            ret.append(resp)

    return ret


def _restructure_entries(entries: list[MediaEntry]) -> dict[int, InnerMediaEntry]:
    return {entry["media"]["id"]: entry["media"] for entry in entries}


def _get_common_planning(data: list[AnilistResponse]) -> dict[int, InnerMediaEntry]:
    user1_data, user2_data = data

    user1_entries = _restructure_entries(user1_data["data"]["MediaListCollection"]["lists"][0]["entries"])
    user2_entries = _restructure_entries(user2_data["data"]["MediaListCollection"]["lists"][0]["entries"])

    all_anime = user1_entries | user2_entries
    common_anime = user1_entries.keys() & user2_entries.keys()

    return {id_: all_anime[id_] for id_ in common_anime}


@app.get("/{user1}/{user2}")
async def index(request: Request, user1: str, user2: str) -> Response:
    data = await _fetch_user_entries(user1, user2)

    matching_items = _get_common_planning(data)

    if not matching_items:
        return Response("No planning anime in common :(", status_code=405, media_type="text/plain")

    formatted = format_entries_as_table(matching_items)

    return Response(formatted, media_type="text/html")
