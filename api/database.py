"""SQLite connection helpers and the relational schema."""
import os
import sqlite3
from collections.abc import AsyncIterator

DB_PATH = os.getenv("REELCLUB_DB", "reelclub.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id  TEXT NOT NULL UNIQUE,
    username    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS titles (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tmdb_id       INTEGER NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    release_year INTEGER,
    overview      TEXT,
    poster_url    TEXT,
    runtime       INTEGER
);

CREATE TABLE IF NOT EXISTS ratings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    member_id   INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    title_id    INTEGER NOT NULL REFERENCES titles(id)  ON DELETE CASCADE,
    score       REAL NOT NULL CHECK (score BETWEEN 1 AND 10),
    review      TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (guild_id, member_id, title_id)
);

CREATE INDEX IF NOT EXISTS idx_ratings_guild_title ON ratings (guild_id, title_id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


async def get_db() -> AsyncIterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()