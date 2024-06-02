from __future__ import annotations

from functools import reduce
from operator import or_, and_
from enum import Enum
from typing import TYPE_CHECKING, Sequence

import httpx
from litestar import Litestar, MediaType, Response, get, status_codes
from litestar.middleware.rate_limit import RateLimitConfig

if TYPE_CHECKING:
    from .types_.responses import AnilistError, AnilistErrorResponse, AnilistResponse, InnerMediaEntry, MediaEntry

USER_QUERY = """
user{number}: MediaListCollection(userName: $username{number}, status: $status, type: ANIME) {{
    lists {{
        entries {{
            media {{
                id
                title {{
                    romaji
                    english
                    native
                }}
                siteUrl
            }}
        }}
    }}
}}
"""

QUERY = """
query ({parameters}, $status: MediaListStatus) {{
    {subqueries}
}}
"""

OPENGRAPH_HEAD = """
<!DOCTYPE html>
<html prefix="og: https://ogp.me/ns#">
<head>
    <meta charset="UTF-8" />
    <title>Hi</title>
    <meta property="og:title" content="Common '{status}' anilist entries for {users}." />
    <meta property="og:description" content="They currently have {mutual} mutual entries." />
    <meta property="og:locale" content="en_GB" />
    <meta property="og:type" content="website" />
</head>
</html>
"""

HEADINGS = ["romaji", "english", "native"]

TABLE = """
<table>
<thead>
<tr>
<th>Media ID</th>
{included}
<th>URL</th>
</tr>
</thead>
<tbody>
{{body}}
</tbody>
</table>
"""

ROW = """
<tr>
<td>{{id}}</td>
{included}
<td><a href="{{siteUrl}}">Anilist</a></td>
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


def format_entries_as_table(entries: dict[int, InnerMediaEntry], excluded: list[str]) -> str:
    included = "\n".join(f"<td>{{title[{h}]}}</td>" for h in HEADINGS if h not in excluded)
    rows = [ROW.format(included=included).format_map(entry) for entry in entries.values()]
    formatted_headings = "\n".join(f"<th>{h.title()}</th>" for h in HEADINGS if h not in excluded)
    return TABLE.format(included=formatted_headings).format(body="\n".join(rows))


async def _fetch_user_entries(*usernames: str, status: Status) -> AnilistResponse | AnilistErrorResponse:
    parameters = ", ".join(f"$username{n}: String" for n in range(len(usernames)))
    subqueries = "".join(USER_QUERY.format(number=n) for n in range(len(usernames)))
    variables = {f"username{n}": name for n, name in enumerate(usernames)}
    variables.update(status=status.value)
    query = QUERY.format(parameters=parameters, subqueries=subqueries)

    async with httpx.AsyncClient() as session:
        resp = await session.post("https://graphql.anilist.co", json={"query": query, "variables": variables})

        return resp.json()


def _restructure_entries(entries: list[MediaEntry]) -> dict[int, InnerMediaEntry]:
    return {entry["media"]["id"]: entry["media"] for entry in entries}


def _get_common_planning(data: AnilistResponse) -> dict[int, InnerMediaEntry]:

    media_entries: list[dict[int, InnerMediaEntry]] = []

    for index, item in enumerate(data["data"].values()):
        if not item:
            raise NoPlanningData(index)

        media_entries.append(_restructure_entries(item["lists"][0]["entries"]))

    all_anime: dict[int, InnerMediaEntry] = reduce(or_, media_entries)
    common_anime: set[int] = reduce(and_, map(lambda d: d.keys(), media_entries))

    return {id_: all_anime[id_] for id_ in common_anime}


def _handle_errors(errors: list[AnilistError], *users: str) -> list[str]:
    missing_users: list[str] = []
    for error in errors:
        if error["message"] == "User not found" and error["status"] == 404:
            for location in error["locations"]:
                line = location["line"] - 4
                index = line // len(USER_QUERY.splitlines())
                missing_users.append(users[index])
    return missing_users


def _human_join(seq: Sequence[str], /, *, delimiter: str = ", ", final: str = "and") -> str:
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    return delimiter.join(seq[:-1]) + f" {final} {seq[-1]}"


@get("/")
async def index() -> Response[str]:
    return Response(
        "Did you forget to add path parameters? Like <url>/User1/User2?",
        media_type=MediaType.TEXT,
        status_code=status_codes.HTTP_400_BAD_REQUEST,
    )


@get("/{user_list:path}")
async def get_matches(user_list: str, exclude: list[str] | None = None, status: str = "planning") -> Response[str]:
    users = list(set([user.casefold() for user in user_list.lstrip("/").split("/")]))

    if len(users) <= 1:
        return Response(
            f"Only {len(users)} user(s) provided. You must provide at least two, for example: <url>/user1/user2/etc...",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_400_BAD_REQUEST,
        )

    for user in users:
        if not user.isalnum() or len(user) > 20:
            return Response(
                f"User {user} is not a valid AniList username.",
                media_type=MediaType.TEXT,
                status_code=status_codes.HTTP_400_BAD_REQUEST,
            )

    try:
        selected_status = Status[status.casefold()]
    except KeyError:
        _statuses = "\n".join(item.name for item in Status)
        return Response(f"Sorry, your chosen status of {status} is not valid. Please choose from:-\n\n{_statuses}")

    excluded = list(set([ex.casefold() for ex in exclude or []]))

    faulty = [ex for ex in excluded if ex not in HEADINGS]

    if faulty:
        return Response(
            f"Unknown excluded headings: {_human_join(faulty)}. Supported: {_human_join(HEADINGS)}",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_400_BAD_REQUEST,
        )

    data = await _fetch_user_entries(*users, status=selected_status)

    if errors := data.get("errors"):
        errored_users = _handle_errors(errors, *users)

        fmt = ", ".join(errored_users)
        return Response(
            f"Sorry, it seems that user(s) {fmt} are not found.",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    try:
        matching_items = _get_common_planning(data)  # type: ignore # the type is resolved above.
    except NoPlanningData as err:
        errored_user = users[err.user]
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

    head = OPENGRAPH_HEAD.format(users=_human_join(users), mutual=len(matching_items), status=selected_status.value.title())
    formatted = format_entries_as_table(matching_items, excluded=excluded)

    return Response(head + "\n" + formatted, media_type=MediaType.HTML, status_code=status_codes.HTTP_200_OK)


RL_CONFIG = RateLimitConfig(
    ("second", 1),
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)


app = Litestar(route_handlers=[index, get_matches], middleware=[RL_CONFIG.middleware])
