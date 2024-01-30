from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import Response

if TYPE_CHECKING:
    from .types_.responses import AnilistError, AnilistErrorResponse, AnilistResponse, InnerMediaEntry, MediaEntry

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

OPENGRAPH_HEAD = """
<!DOCTYPE html>
<html prefix="og: https://ogp.me/ns#">
<head>
    <meta charset="UTF-8" />
    <title>Hi</title>
    <meta property="og:title" content="{user1} and {user2}'s mutual 'Planning' anilist entries." />
    <meta property="og:description" content="They both currently have {mutual} mutual entries." />
    <meta property="og:locale" content="en_GB" />
    <meta property="og:type" content="website" />
</head>
</html>
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


class NoPlanningData(ValueError):
    def __init__(self, user: int, *args: object) -> None:
        self.user = user
        super().__init__(*args)


def format_entries_as_table(entries: dict[int, InnerMediaEntry]) -> str:
    rows = [ROW.format_map(entry) for entry in entries.values()]
    return TABLE.format(body="\n".join(rows))


async def _fetch_user_entries(*usernames: str) -> AnilistResponse | AnilistErrorResponse:
    username1, username2 = usernames

    async with aiohttp.ClientSession() as session, session.post(
        "https://graphql.anilist.co",
        json={"query": QUERY, "variables": {"username1": username1, "username2": username2}},
    ) as resp:
        return await resp.json()


def _restructure_entries(entries: list[MediaEntry]) -> dict[int, InnerMediaEntry]:
    return {entry["media"]["id"]: entry["media"] for entry in entries}


def _get_common_planning(data: AnilistResponse) -> dict[int, InnerMediaEntry]:
    user1_data = data["data"]["user1"]["lists"]
    user2_data = data["data"]["user2"]["lists"]

    if not user1_data:
        raise NoPlanningData(1)
    elif not user2_data:
        raise NoPlanningData(2)

    user1_entries = _restructure_entries(user1_data[0]["entries"])
    user2_entries = _restructure_entries(user2_data[0]["entries"])

    all_anime = user1_entries | user2_entries
    common_anime = user1_entries.keys() & user2_entries.keys()

    return {id_: all_anime[id_] for id_ in common_anime}


def _handle_errors(errors: list[AnilistError], user1: str, user2: str) -> list[str]:
    missing_users: list[str] = []
    for error in errors:
        if error["message"] == "User not found":
            for location in error["locations"]:
                if location["column"] == 2:
                    missing_users.append(user1)
                elif location["column"] == 17:
                    missing_users.append(user2)

    return missing_users


@app.get("/")
async def index() -> Response:
    return Response("Did you forget to add path parameters? Like <url>/User1/User2?", media_type="text/plain")


@app.get("/{user1}/{user2}")
async def get_matches(request: Request, user1: str, user2: str) -> Response:
    if user1.casefold() == user2.casefold():
        return Response("Haha, you're really funny.", media_type="text/plain")

    data = await _fetch_user_entries(user1.casefold(), user2.casefold())

    if errors := data.get("errors"):
        errored_users = _handle_errors(errors, user1, user2)

        fmt = ", ".join(errored_users)
        return Response(f"Sorry, it seems that user(s) {fmt} are not found.")

    try:
        matching_items = _get_common_planning(data)  # type: ignore # the type is resolved above.
    except NoPlanningData as err:
        errored_user = user1 if err.user == 1 else user2
        return Response(f"Sorry, but {errored_user} has no Planning entries!", media_type="text/plain")

    if not matching_items:
        return Response("No planning anime in common :(", status_code=405, media_type="text/plain")

    head = OPENGRAPH_HEAD.format(user1=user1, user2=user2, mutual=len(matching_items))
    formatted = format_entries_as_table(matching_items)

    return Response(head + "\n" + formatted, media_type="text/html")
