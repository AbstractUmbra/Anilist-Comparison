from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from .types_.responses import AnilistResponse, InnerMediaEntry, MediaEntry

app = FastAPI(debug=False, title="Welcome!", version="0.0.1", openapi_url=None, redoc_url=None, docs_url=None)

QUERY = """
query ($username1: String, $username2: String) {
    user1: MediaListCollection(userName: $username1, status: PLANNING, type: ANIME) {
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
    user2: MediaListCollection(userName: $username2, status: PLANNING, type: ANIME) {
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


async def _fetch_user_entries(*usernames: str) -> AnilistResponse:
    username1, username2 = usernames

    async with aiohttp.ClientSession() as session, session.post(
        "https://graphql.anilist.co",
        json={"query": QUERY, "variables": {"username1": username1, "username2": username2}},
    ) as resp:
        return await resp.json()


def _restructure_entries(entries: list[MediaEntry]) -> dict[int, InnerMediaEntry]:
    return {entry["media"]["id"]: entry["media"] for entry in entries}


def _get_common_planning(data: AnilistResponse) -> dict[int, InnerMediaEntry]:
    user1_data = data["data"]["user1"]
    user2_data = data["data"]["user2"]

    user1_entries = _restructure_entries(user1_data["lists"][0]["entries"])
    user2_entries = _restructure_entries(user2_data["lists"][0]["entries"])

    all_anime = user1_entries | user2_entries
    common_anime = user1_entries.keys() & user2_entries.keys()

    return {id_: all_anime[id_] for id_ in common_anime}


@app.get("/")
async def index() -> Response:
    return Response("Did you forget to add path parameters? Like <url>/User1/User2?", media_type="text/plain")


@app.get("/{user1}/{user2}")
async def get_matches(request: Request, user1: str, user2: str) -> Response:
    data = await _fetch_user_entries(user1, user2)

    matching_items = _get_common_planning(data)

    if not matching_items:
        return Response("No planning anime in common :(", status_code=405, media_type="text/plain")

    formatted = format_entries_as_table(matching_items)

    return Response(formatted, media_type="text/html")
