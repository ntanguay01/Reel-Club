"""ReelClub API: the server tier. Exposes CRUD for ratings and movie lookup."""
import os
import sqlite3
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP, Decimal

from dotenv import load_dotenv

load_dotenv()  # must run before the imports below read environment variables

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

from . import tmdb  # noqa: E402
from .database import get_db, init_db  # noqa: E402


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid or missing API key.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ReelClub API", lifespan=lifespan, dependencies=[Depends(require_api_key)])


# ----------------------------------------------------------------- models
def round_half_up(value: float) -> float:
    """Round to one decimal the way people expect: 8.25 becomes 8.3.
    (Python's built-in round() sends exact halves to the even digit, so 8.25 would become 8.2.)"""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def one_decimal(value: float | None) -> float | None:
    """Scores may have at most one decimal place (7.5 is fine, 7.55 is not)."""
    if value is None:
        return None
    if abs(value * 10 - round(value * 10)) > 1e-6:
        raise ValueError("Score can have at most one decimal place, like 7.5.")
    return round(value, 1)


class RatingCreate(BaseModel):
    guild_id: str
    discord_id: str
    username: str
    tmdb_id: int
    score: float = Field(ge=1, le=10)
    review: str | None = Field(default=None, max_length=1000)

    _check_score = field_validator("score")(one_decimal)


class RatingUpdate(BaseModel):
    discord_id: str  # must match the rating's owner
    score: float | None = Field(default=None, ge=1, le=10)
    review: str | None = Field(default=None, max_length=1000)

    _check_score = field_validator("score")(one_decimal)


# ---------------------------------------------------------------- helpers
RATING_SELECT = """
    SELECT r.id, r.guild_id, m.discord_id, m.username,
           t.tmdb_id, t.title, t.release_year,
           r.score, r.review, r.created_at, r.updated_at
    FROM ratings r
    JOIN members m ON m.id = r.member_id
    JOIN titles  t ON t.id = r.title_id
"""


def fetch_rating(db: sqlite3.Connection, rating_id: int) -> dict:
    row = db.execute(f"{RATING_SELECT} WHERE r.id = ?", (rating_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Rating not found.")
    return dict(row)


def upsert_member(db: sqlite3.Connection, discord_id: str, username: str) -> int:
    db.execute(
        """INSERT INTO members (discord_id, username) VALUES (?, ?)
           ON CONFLICT(discord_id) DO UPDATE SET username = excluded.username""",
        (discord_id, username),
    )
    return db.execute("SELECT id FROM members WHERE discord_id = ?", (discord_id,)).fetchone()["id"]


def upsert_title(db: sqlite3.Connection, movie: dict) -> int:
    db.execute(
        """INSERT INTO titles (tmdb_id, title, release_year, overview, poster_url, runtime)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(tmdb_id) DO UPDATE SET
               title = excluded.title,
               release_year = excluded.release_year,
               overview = excluded.overview,
               poster_url = excluded.poster_url,
               runtime = COALESCE(excluded.runtime, titles.runtime)""",
        (
            movie["tmdb_id"],
            movie["title"],
            movie.get("release_year"),
            movie.get("overview"),
            movie.get("poster_url"),
            movie.get("runtime"),
        ),
    )
    return db.execute("SELECT id FROM titles WHERE tmdb_id = ?", (movie["tmdb_id"],)).fetchone()["id"]


# ----------------------------------------------------------- title lookup
@app.get("/titles/search")
async def search_titles(
    query: str = Query(min_length=1, max_length=100), year: int | None = None
):
    """Search TMDB for movies by name (optionally narrowed by release year)."""
    return await tmdb.search_movies(query, year)


@app.get("/titles/{tmdb_id}")
async def get_title(
    tmdb_id: int, guild_id: str | None = None, db: sqlite3.Connection = Depends(get_db)
):
    """Full movie details from TMDB, cached in our titles table.
    Pass guild_id to include that server's average rating."""
    movie = await tmdb.get_movie(tmdb_id)
    with db:
        upsert_title(db, movie)
    if guild_id:
        row = db.execute(
            """SELECT AVG(r.score) AS average, COUNT(*) AS n
               FROM ratings r JOIN titles t ON t.id = r.title_id
               WHERE t.tmdb_id = ? AND r.guild_id = ?""",
            (tmdb_id, guild_id),
        ).fetchone()
        movie["club_rating"] = {
            "average": round_half_up(row["average"]) if row["average"] is not None else None,
            "count": row["n"],
        }
    return movie


# ---------------------------------------------------------------- ratings
@app.post("/ratings", status_code=201)
async def create_rating(payload: RatingCreate, db: sqlite3.Connection = Depends(get_db)):
    title = db.execute("SELECT id FROM titles WHERE tmdb_id = ?", (payload.tmdb_id,)).fetchone()
    if title:
        title_id = title["id"]
    else:
        movie = await tmdb.get_movie(payload.tmdb_id)
        with db:
            title_id = upsert_title(db, movie)
    try:
        with db:
            member_id = upsert_member(db, payload.discord_id, payload.username)
            cur = db.execute(
                """INSERT INTO ratings (guild_id, member_id, title_id, score, review)
                   VALUES (?, ?, ?, ?, ?)""",
                (payload.guild_id, member_id, title_id, payload.score, payload.review),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "You have already rated this movie. Use /editrating to change it.")
    return fetch_rating(db, cur.lastrowid)


@app.get("/ratings")
async def list_ratings(
    guild_id: str,
    tmdb_id: int | None = None,
    discord_id: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    db: sqlite3.Connection = Depends(get_db),
):
    where, params = ["r.guild_id = ?"], [guild_id]
    if tmdb_id is not None:
        where.append("t.tmdb_id = ?")
        params.append(tmdb_id)
    if discord_id is not None:
        where.append("m.discord_id = ?")
        params.append(discord_id)
    rows = db.execute(
        f"{RATING_SELECT} WHERE {' AND '.join(where)} ORDER BY r.updated_at DESC, r.id DESC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/ratings/{rating_id}")
async def get_rating(rating_id: int, db: sqlite3.Connection = Depends(get_db)):
    return fetch_rating(db, rating_id)


@app.put("/ratings/{rating_id}")
async def update_rating(
    rating_id: int, payload: RatingUpdate, db: sqlite3.Connection = Depends(get_db)
):
    existing = fetch_rating(db, rating_id)
    if existing["discord_id"] != payload.discord_id:
        raise HTTPException(403, "You can only edit your own ratings.")
    sent = payload.model_fields_set
    score = payload.score if payload.score is not None else existing["score"]
    review = payload.review if "review" in sent else existing["review"]
    with db:
        db.execute(
            "UPDATE ratings SET score = ?, review = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (score, review, rating_id),
        )
    return fetch_rating(db, rating_id)


@app.delete("/ratings/{rating_id}", status_code=204)
async def delete_rating(
    rating_id: int, discord_id: str, db: sqlite3.Connection = Depends(get_db)
):
    existing = fetch_rating(db, rating_id)
    if existing["discord_id"] != discord_id:
        raise HTTPException(403, "You can only delete your own ratings.")
    with db:
        db.execute("DELETE FROM ratings WHERE id = ?", (rating_id,))
    return Response(status_code=204)