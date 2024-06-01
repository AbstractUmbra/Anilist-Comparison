from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import httpx
from litestar import Litestar, MediaType, Response, get, status_codes
from litestar.middleware.rate_limit import RateLimitConfig

if TYPE_CHECKING:
    from .types_.responses import AnilistError, AnilistErrorResponse, AnilistResponse, InnerMediaEntry, MediaEntry

QUERY = """
query ($username1: String, $username2: String, $status: MediaListStatus) {
    user1: MediaListCollection(userName: $username1, status: $status, type: ANIME) {
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
    user2: MediaListCollection(userName: $username2, status: $status, type: ANIME) {
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
    <meta property="og:title" content="{user1} and {user2}'s mutual '{status}' anilist entries." />
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


class Status(Enum):
    planning = "PLANNING"
    current = "CURRENT"
    completed = "COMPLETED"
    dropped = "DROPPED"
    paused = "PAUSED"
    repeating = "REPEATING"


def format_entries_as_table(entries: dict[int, InnerMediaEntry]) -> str:
    rows = [ROW.format_map(entry) for entry in entries.values()]
    return TABLE.format(body="\n".join(rows))


async def _fetch_user_entries(*usernames: str, status: Status) -> AnilistResponse | AnilistErrorResponse:
    username1, username2 = usernames

    async with httpx.AsyncClient() as session:
        resp = await session.post(
            "https://graphql.anilist.co",
            json={"query": QUERY, "variables": {"username1": username1, "username2": username2, "status": status.value}},
        )

        return resp.json()


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
        if error["message"] == "User not found" and error["status"] == 404:
            for location in error["locations"]:
                print(location, flush=True)
                if location["line"] == 3:
                    missing_users.append(user1)
                elif location["line"] == 18:
                    missing_users.append(user2)

    return missing_users


@get("/")
async def index() -> Response[str]:
    return Response(
        "Did you forget to add path parameters? Like <url>/User1/User2?",
        media_type=MediaType.TEXT,
        status_code=status_codes.HTTP_400_BAD_REQUEST,
    )


@get("/{user1:str}/{user2:str}")
async def get_matches(user1: str, user2: str, status: str = "planning") -> Response[str]:
    if user1.casefold() == user2.casefold():
        return Response(
            "Haha, you're really funny.", media_type=MediaType.TEXT, status_code=status_codes.HTTP_418_IM_A_TEAPOT
        )

    try:
        selected_status = Status[status.casefold()]
    except KeyError:
        _statuses = "\n".join(item.name for item in Status)
        return Response(f"Sorry, your chosen status of {status} is not valid. Please choose from:-\n\n{_statuses}")

    data = await _fetch_user_entries(user1.casefold(), user2.casefold(), status=selected_status)

    if errors := data.get("errors"):
        errored_users = _handle_errors(errors, user1, user2)

        fmt = ", ".join(errored_users)
        return Response(
            f"Sorry, it seems that user(s) {fmt} are not found.",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    try:
        matching_items = _get_common_planning(data)  # type: ignore # the type is resolved above.
    except NoPlanningData as err:
        errored_user = user1 if err.user == 1 else user2
        return Response(
            f"Sorry, but {errored_user} has no {selected_status.value.lower()} entries!",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_412_PRECONDITION_FAILED,
        )

    if not matching_items:
        return Response(
            f"No {selected_status.value.lower()} anime in common :(",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_412_PRECONDITION_FAILED,
        )

    head = OPENGRAPH_HEAD.format(user1=user1, user2=user2, mutual=len(matching_items), status=selected_status.value.title())
    formatted = format_entries_as_table(matching_items)

    return Response(head + "\n" + formatted, media_type=MediaType.HTML, status_code=status_codes.HTTP_200_OK)


RL_CONFIG = RateLimitConfig(
    ("second", 1),
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)

app = Litestar(route_handlers=[index, get_matches], middleware=[RL_CONFIG.middleware])
