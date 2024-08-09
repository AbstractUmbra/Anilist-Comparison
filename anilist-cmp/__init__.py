from __future__ import annotations

import pathlib
from collections import ChainMap
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx
from litestar import Litestar, MediaType, Response, get, post, status_codes
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.params import Body  # noqa: TCH002 # required at runtime
from litestar.response import Template
from litestar.template import TemplateConfig

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Annotated

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


@dataclass
class QueryData:
    users: list[str]
    status: str = "planning"


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


class APIException(Exception):
    def __init__(self, *, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(self.message)

    def to_json(self) -> dict[str, str]:
        return {"error": self.message}

    def to_text(self) -> str:
        return self.message


class TooLittleUsers(APIException):
    def __init__(self, users: Iterable[str], /) -> None:
        self.users = users
        super().__init__(status_code=400, message="You must provide at least 2 unique users for comparison.")


class InvalidAniListUsername(APIException):
    def __init__(self, user: str) -> None:
        self.user = user
        super().__init__(status_code=400, message=f"User {user!r} is not a valid AniList username.")


def _parse_users(users: Iterable[str]) -> None:
    cleaned = set(users)
    if len(cleaned) < 2:
        raise TooLittleUsers(cleaned)

    for user in users:
        if not user.isalnum() or len(user) > 20:
            raise InvalidAniListUsername(user)


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


@post("/")
async def get_matches_headless(data: Annotated[QueryData, Body(title="Query user's anilists")]) -> Response[dict[str, Any]]:
    try:
        _parse_users(data.users)
    except TooLittleUsers as err:
        return Response({"error": err.message}, media_type=MediaType.JSON, status_code=err.status_code)
    except InvalidAniListUsername as err:
        return Response({"error": err.message}, media_type=MediaType.JSON, status_code=err.status_code)

    try:
        selected_status = Status[data.status.lower()]
    except KeyError:
        return Response(
            {"error": "Invalid status provided: {data.status!r}", "accepted_statuses": [status.name for status in Status]},
            media_type=MediaType.JSON,
            status_code=400,
        )

    anilist_data = await _fetch_user_entries(*data.users, status=selected_status)

    if errors := anilist_data.get("errors"):
        errored_users = _handle_errors(errors, *data.users)
        return Response(
            {"error": "Some user(s) were not found in AniList.", "missing_users": errored_users},
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    try:
        matching_items = _get_common_anime(anilist_data)  # type: ignore # the type is resolved above.
    except EmptyAnimeList as err:
        errored_user = data.users[err.user]
        return Response(
            {
                "error": "A user does not have any entries with the selected status",
                "user": errored_user,
                "status": selected_status.value.lower(),
            },
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    if not matching_items:
        return Response(
            {
                "error": "The provided users have no commonality with the provided status",
                "status": selected_status.value.lower(),
            },
            media_type=MediaType.JSON,
            status_code=status_codes.HTTP_404_NOT_FOUND,
        )

    context = {
        "entries": sorted(matching_items.values(), key=lambda entry: entry["id"]),
        "status": selected_status,
    }
    return Response(context, media_type=MediaType.JSON, status_code=status_codes.HTTP_200_OK)


@get("/{user_list:path}")
async def get_matches(user_list: str, status: str = "planning") -> Response[str] | Template:
    usernames = [username for username in user_list.split("/") if username]
    users = list({user.lower() for user in usernames})

    try:
        _parse_users(users)
    except TooLittleUsers as err:
        return Response(err.to_text(), media_type=MediaType.TEXT, status_code=err.status_code)
    except InvalidAniListUsername as err:
        return Response(err.to_text(), media_type=MediaType.TEXT, status_code=err.status_code)

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

    context = {
        "entries": sorted(matching_items.values(), key=lambda entry: entry["id"]),
        "status": selected_status,
        "description": f"Common anime for {_human_join(usernames)}",
    }
    return Template(template_name="page.html", context=context)


RL_CONFIG = RateLimitConfig(
    ("minute", 5),
    exclude=["favicon.ico"],
    rate_limit_limit_header_key="X-Ratelimit-Limit",
    rate_limit_policy_header_key="X-Ratelimit-Policy",
    rate_limit_remaining_header_key="X-Ratelimit-Remaining",
    rate_limit_reset_header_key="X-Ratelimit-Reset",
)

template_directory = pathlib.Path(__file__).parent / "templates"
app = Litestar(
    route_handlers=[index, get_matches, get_matches_headless],
    middleware=[RL_CONFIG.middleware],
    template_config=TemplateConfig(directory=template_directory, engine=JinjaTemplateEngine),
    include_in_schema=False,
    openapi_config=None,
)
