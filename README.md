# ReelClub

A Discord bot that helps a movie club decide what to watch next. Members can get movie recommendations by genre, look up details on any movie, save movies to a private watchlist, and rate and review what they have watched.

The project is built as three tiers, all in Python:

```
Discord  ->  bot/ (discord.py)  ->  api/ (FastAPI)  ->  SQLite database
                                        |
                                        +->  TMDB (movie data)
```

The bot never touches the database. Every read and write goes through the API.

## Features

### Built

| Command | What it does | CRUD |
|---|---|---|
| `/info title` | Poster, synopsis, runtime, director, cast, genres, streaming services, club rating | Read |
| `/rate title score [review]` | Rate a movie 1 to 10 (one decimal allowed, like 7.5) with an optional review | Create |
| `/ratings title` | Everyone's ratings and the club average for a movie | Read |
| `/myratings` | Movies you have rated in this server | Read |
| `/editrating title [score] [review]` | Change your score or review | Update |
| `/deleterating title` | Remove your rating | Delete |

Title fields autocomplete from TMDB as you type. A member can rate a movie once per server, and ratings are visible to the whole server.

### Planned (not built yet)

| Command | What it will do | CRUD |
|---|---|---|
| `/recommend genre:<genre>` | Pick a genre from the list Discord shows and get 10 movies. Results are varied, filtered for quality, and skip movies you have already rated or saved | Read |
| `/watchlist add title` | Save a movie to your watchlist | Create |
| `/watchlist view` | See your saved movies, unwatched first | Read |
| `/watchlist watched title` | Mark a movie as watched | Update |
| `/watchlist note title note` | Add or change a note on a saved movie | Update |
| `/watchlist remove title` | Remove a movie from your list | Delete |

Each member's watchlist is private: only that member can see it, and the bot's replies to watchlist commands are visible only to them.

## API endpoints

### Built

| Method | Path | Purpose |
|---|---|---|
| GET | `/titles/search?query=&year=` | Search TMDB |
| GET | `/titles/{tmdb_id}?guild_id=` | Movie details (cached in `titles`) plus server average |
| POST | `/ratings` | Create a rating |
| GET | `/ratings?guild_id=&tmdb_id=&discord_id=&limit=` | List ratings |
| GET | `/ratings/{id}` | One rating |
| PUT | `/ratings/{id}` | Update (owner only) |
| DELETE | `/ratings/{id}?discord_id=` | Delete (owner only) |

### Planned

| Method | Path | Purpose |
|---|---|---|
| GET | `/genres` | List the movie genres available from TMDB |
| GET | `/recommendations?genre=&guild_id=&discord_id=` | 10 movies in a genre, skipping ones the member has rated or saved |
| POST | `/watchlist` | Add a movie to a member's watchlist |
| GET | `/watchlist?guild_id=&discord_id=` | List a member's watchlist |
| PUT | `/watchlist/{id}` | Mark as watched or change the note (owner only) |
| DELETE | `/watchlist/{id}?discord_id=` | Remove a movie (owner only) |

Interactive docs for the built endpoints are at `http://127.0.0.1:8000/docs` once the API is running.

## Database tables

| Table | Purpose | Status |
|---|---|---|
| `members` | Discord users | Built |
| `titles` | Cached TMDB movies | Built |
| `ratings` | A member's score and review for a title, unique per server | Built |
| `watchlist` | A member's saved movies, with a watched flag and an optional note, unique per server | Planned |

## Setup

1. Python 3.10 or newer. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. Run the API, then the bot, in two terminals from this folder:
   ```
   uvicorn api.main:app --reload
   python -m bot.main
   ```

Set `DISCORD_GUILD_ID` in `.env` while developing so slash commands show up instantly.

## Project layout

```
api/database.py   schema and connections
api/tmdb.py       TMDB wrapper
api/main.py       FastAPI routes
bot/api_client.py HTTP client for the API
bot/main.py       slash commands
```

The recommender and watchlist will add to these files rather than create new ones, unless the code grows enough to split.

## Known limitations

- A review can be changed with `/editrating` but not cleared, because leaving the review blank means "do not change it."
- The bot and API have only been tested with TMDB mocked. Live testing against Discord and TMDB is the next step.