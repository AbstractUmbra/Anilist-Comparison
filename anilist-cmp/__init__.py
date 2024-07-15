from __future__ import annotations

import pathlib
from collections import ChainMap
from enum import Enum
from typing import TYPE_CHECKING

import httpx
from litestar import Litestar, MediaType, Response, get, status_codes
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.response import Template
from litestar.template import TemplateConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

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


class EmptyAnimeList(ValueError):
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


def _get_common_anime(data: AnilistResponse) -> dict[int, InnerMediaEntry]:
    media_entries: list[dict[int, InnerMediaEntry]] = []

    for index, item in enumerate(data["data"].values()):
        if not item or not item["lists"]:
            raise EmptyAnimeList(index)

        media_entries.append(_restructure_entries(item["lists"][0]["entries"]))

    all_anime = ChainMap(*media_entries)
    common_anime = set(all_anime).intersection(*media_entries)

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
async def get_matches(user_list: str, status: str = "planning") -> Response[str] | Template:
    usernames = [username for username in user_list.split('/') if username]
    users = list({user.lower() for user in usernames})

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
        selected_status = Status[status.lower()]
    except KeyError:
        _statuses = "\n".join(item.name for item in Status)
        return Response(f"Sorry, your chosen status of {status} is not valid. Please choose from:-\n\n{_statuses}")

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
        matching_items = _get_common_anime(data)  # type: ignore # the type is resolved above.
    except EmptyAnimeList as err:
        errored_user = users[err.user]
        return Response(
            f"Sorry, but {errored_user} has no {selected_status.value.lower()} entries!",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    if not matching_items:
        return Response(
            f"No {selected_status.value.lower()} anime in common :(",
            media_type=MediaType.TEXT,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    context = dict(entries=sorted(matching_items.values(), key=lambda entry: entry['id']), status=selected_status,
                   description=f'Common anime for {_human_join(usernames)}')
    return Template(template_name='page.html', context=context)


RL_CONFIG = RateLimitConfig(
    ("second", 1),
    exclude=["favicon.ico"],
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)

template_directory = pathlib.Path(__file__).parent / 'templates'
app = Litestar(
    route_handlers=[index, get_matches],
    middleware=[RL_CONFIG.middleware],
    template_config=TemplateConfig(directory=template_directory, engine=JinjaTemplateEngine),
)
