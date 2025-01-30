import uvicorn

has_uvloop = True
try:
    import uvloop as uvloop
except ModuleNotFoundError:
    has_uvloop = False


if __name__ == "__main__":
    uvicorn.run(
        "anilist-cmp:app",
        host="0.0.0.0",  # noqa: S104 # allowed in this case as we containerize the project
        port=8080,
        workers=2,
        loop="uvloop" if has_uvloop else "auto",
        proxy_headers=True,
        server_header=True,
        date_header=True,
    )
