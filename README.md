# anilistcmp

A small website that compares and presents overlapping items between two people's anilist profiles.

This was made with the intention of helping people find something to watch together.

This is running at https://anilist.abstractumbra.dev/, you must provide at least two usernames within the path to query, like so:
https://anilist.abstractumbra.dev/AbstractUmbra/OtherUmbra/etc...

By default this will compare entries in the "Planning" category.
You can add a `status` query parameter to further refine what category you wish to see!

You can also pass one (or more) `exclude` query parameters to exclude a column.

The `?status=` parameter accepts the following values:-
```
planning (the default)
current
completed
dropped
paused
repeating
```

The `?exclude=` parameter accepts the following values:-
```
romaji
english
native
```


## Running your own

The provided docker-compose file should work on it's own, otherwise just clone the repository and install the necessary dependencies and run the `main.py` with a Python version >= 3.11
