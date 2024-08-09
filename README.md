# anilistcmp

A small website that compares and presents overlapping items between two people's anilist profiles.

This was made with the intention of helping people find something to watch together.

This is running at https://anilist.abstractumbra.dev/, you must provide at least two usernames within the path to query, like so:
https://anilist.abstractumbra.dev/AbstractUmbra/OtherUmbra/etc...

By default this will compare entries in the "Planning" category.
You can add a `status` query parameter to further refine what category you wish to see!

The `?status=` parameter accepts the following values:-
```
planning (the default)
current
completed
dropped
paused
repeating
```

### JSON API

This project now exposes a headless JSON API on request. This is available on the following:
```
POST https://anilist.abstractumbra.dev/
{
    "users": ["User1", "User2"], # supports N many users
    "status": "planning" # defaults to 'planning'
}
```

## Running your own

The provided docker-compose file should work on its own.

To run in development mode, use
```
litestar --app anilist-cmp:app run --debug --reload
```
