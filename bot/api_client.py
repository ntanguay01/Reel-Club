"""HTTP client the bot uses to talk to the ReelClub API. The bot never touches the database."""
import asyncio

import aiohttp


class APIError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class ReelClubAPI:
    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        self.session = aiohttp.ClientSession(
            headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            async with self.session.request(method, f"{self.base_url}{path}", **kwargs) as resp:
                status = resp.status
                if status == 204:
                    return None
                try:
                    data = await resp.json(content_type=None)
                except ValueError:
                    data = None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise APIError(503, "ReelClub's API is unreachable right now. Try again in a moment.")

        if status >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            if not isinstance(detail, str):
                detail = "That request was not valid." if status == 422 else "Unexpected API error."
            raise APIError(status, detail)
        return data

    # ---- titles
    async def search_titles(self, query: str, year: int | None = None):
        params = {"query": query}
        if year:
            params["year"] = year
        return await self._request("GET", "/titles/search", params=params)

    async def get_title(self, tmdb_id: int, guild_id: str | None = None):
        params = {"guild_id": guild_id} if guild_id else None
        return await self._request("GET", f"/titles/{tmdb_id}", params=params)

    # ---- ratings (full CRUD)
    async def create_rating(self, **payload):
        return await self._request("POST", "/ratings", json=payload)

    async def list_ratings(self, guild_id: str, tmdb_id=None, discord_id=None, limit=25):
        params = {"guild_id": guild_id, "limit": limit}
        if tmdb_id is not None:
            params["tmdb_id"] = tmdb_id
        if discord_id is not None:
            params["discord_id"] = discord_id
        return await self._request("GET", "/ratings", params=params)

    async def update_rating(self, rating_id: int, **payload):
        return await self._request("PUT", f"/ratings/{rating_id}", json=payload)

    async def delete_rating(self, rating_id: int, discord_id: str):
        return await self._request(
            "DELETE", f"/ratings/{rating_id}", params={"discord_id": discord_id}
        )
