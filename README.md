# anilistcmp

A small website that compares and presents overlapping items between two people's anilist profiles.

This was made with the intention of helping people find something to watch together.

This is running at https://anilist.abstractumbra.dev/, you must provide two usernames within the path to query, like so:
https://anilist.abstractumbra.dev/AbstractUmbra/OtherUmbra

By default this will compare entries in the "Planning" category.
You can also add a query parameter to further refine what category you wish to see!

The `?status=` parameter accepts the following values:-
```
planning (the default)
current
completed
dropped
paused
repeating
```

## Running your own

The provided docker-compose file should work on it's own, otherwise just clone the repository and install the necessary dependencies and run the `main.py` with a Python version >= 3.11
