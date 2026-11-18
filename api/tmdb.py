"""Thin wrapper around The Movie Database (TMDB) API, movies only."""
import os

import httpx
from fastapi import HTTPException

TMDB_BASE = "https://api.themoviedb.org/3"
POSTER_BASE = "https://image.tmdb.org/t/p/w500"


def _api_key() -> str:
    key = os.getenv("TMDB_API_KEY")
    if not key:
        raise HTTPException(503, "TMDB_API_KEY is not configured on the server.")
    return key


async def _get(path: str, **params) -> dict:
    params["api_key"] = _api_key()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{TMDB_BASE}{path}", params=params)
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach TMDB.")
    if resp.status_code == 404:
        raise HTTPException(404, "Movie not found on TMDB.")
    if resp.status_code == 401:
        raise HTTPException(503, "TMDB rejected the API key.")
    if resp.status_code != 200:
        raise HTTPException(502, f"TMDB returned an error ({resp.status_code}).")
    return resp.json()


def _year(date_str: str | None) -> int | None:
    if date_str and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


def _poster(path: str | None) -> str | None:
    return f"{POSTER_BASE}{path}" if path else None


async def search_movies(query: str, year: int | None = None) -> list[dict]:
    params = {"query": query, "include_adult": "false"}
    if year:
        params["year"] = year
    data = await _get("/search/movie", **params)
    return [
        {
            "tmdb_id": m["id"],
            "title": m["title"],
            "release_year": _year(m.get("release_date")),
            "overview": m.get("overview") or None,
            "poster_url": _poster(m.get("poster_path")),
        }
        for m in data.get("results", [])[:10]
    ]


async def get_movie(tmdb_id: int) -> dict:
    data = await _get(f"/movie/{tmdb_id}", append_to_response="credits,watch/providers")
    credits = data.get("credits", {})
    director = next(
        (c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"), None
    )
    region = os.getenv("TMDB_WATCH_REGION", "US")
    providers = data.get("watch/providers", {}).get("results", {}).get(region, {})
    return {
        "tmdb_id": data["id"],
        "title": data["title"],
        "release_year": _year(data.get("release_date")),
        "overview": data.get("overview") or None,
        "poster_url": _poster(data.get("poster_path")),
        "runtime": data.get("runtime") or None,
        "genres": [g["name"] for g in data.get("genres", [])],
        "director": director,
        "cast": [c["name"] for c in credits.get("cast", [])[:5]],
        "tmdb_score": round(data["vote_average"], 1) if data.get("vote_average") else None,
        "streaming": [p["provider_name"] for p in providers.get("flatrate", [])],
        "watch_region": region,
    }
