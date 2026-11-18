"""ReelClub Discord bot: the client tier. Captures slash commands and calls the API."""
import logging
import os
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

from .api_client import APIError, ReelClubAPI  # noqa: E402

log = logging.getLogger("reelclub")


class ReelClubBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.api = ReelClubAPI(os.getenv("API_URL", "http://127.0.0.1:8000"), os.getenv("API_KEY"))

    async def setup_hook(self) -> None:
        await self.api.start()
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:  # instant sync to one test server
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:  # global sync (can take up to an hour to appear)
            await self.tree.sync()

    async def close(self) -> None:
        await self.api.close()
        await super().close()


bot = ReelClubBot()


# ---------------------------------------------------------------- helpers
async def title_autocomplete(interaction: discord.Interaction, current: str):
    """Suggest movies as the user types. The value is 'tmdb:<id>' so the pick is unambiguous."""
    if len(current) < 2:
        return []
    try:
        results = await bot.api.search_titles(current)
    except APIError:
        return []
    return [
        app_commands.Choice(
            name=f"{r['title']} ({r['release_year'] or 'n/a'})"[:100], value=f"tmdb:{r['tmdb_id']}"
        )
        for r in results[:10]
    ]


async def resolve_title(text: str) -> int:
    """Turn an autocomplete pick or free-typed title into a TMDB id."""
    text = text.strip()
    if text.startswith("tmdb:") and text[5:].isdigit():
        return int(text[5:])
    results = await bot.api.search_titles(text)
    if not results:
        raise APIError(404, f'No movie found matching "{text}".')
    return results[0]["tmdb_id"]


def label(r: dict) -> str:
    year = f" ({r['release_year']})" if r.get("release_year") else ""
    return f"{r['title']}{year}"


def fmt_runtime(minutes: int) -> str:
    return f"{minutes // 60}h {minutes % 60}m"


def rating_embed(r: dict, heading: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{heading}: {label(r)}",
        description=f"**{r['score']}/10**" + (f"\n{r['review']}" if r.get("review") else ""),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=r["username"])
    return embed


# --------------------------------------------------------------- commands
@bot.tree.command(name="info", description="Look up a movie: poster, cast, runtime, and where to stream it")
@app_commands.describe(title="Start typing a movie title")
@app_commands.autocomplete(title=title_autocomplete)
@app_commands.guild_only()
async def info(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    tmdb_id = await resolve_title(title)
    m = await bot.api.get_title(tmdb_id, guild_id=str(interaction.guild_id))

    embed = discord.Embed(
        title=label(m),
        url=f"https://www.themoviedb.org/movie/{m['tmdb_id']}",
        description=(m.get("overview") or "No synopsis available.")[:1000],
        color=discord.Color.blurple(),
    )
    if m.get("poster_url"):
        embed.set_thumbnail(url=m["poster_url"])
    if m.get("runtime"):
        embed.add_field(name="Runtime", value=fmt_runtime(m["runtime"]))
    if m.get("director"):
        embed.add_field(name="Director", value=m["director"])
    if m.get("genres"):
        embed.add_field(name="Genres", value=", ".join(m["genres"]))
    if m.get("cast"):
        embed.add_field(name="Cast", value=", ".join(m["cast"]), inline=False)
    if m.get("tmdb_score"):
        embed.add_field(name="TMDB score", value=f"{m['tmdb_score']}/10")
    club = m.get("club_rating") or {}
    if club.get("count"):
        embed.add_field(name="Club rating", value=f"{club['average']}/10 ({club['count']} ratings)")
    else:
        embed.add_field(name="Club rating", value="No ratings yet")
    where = ", ".join(m["streaming"]) if m.get("streaming") else "Not available to stream"
    embed.add_field(name=f"Streaming ({m['watch_region']})", value=where, inline=False)
    embed.set_footer(text="Data from TMDB")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="rate", description="Rate a movie from 1 to 10, with an optional review")
@app_commands.describe(title="Start typing a movie title", score="Your score, 1 to 10", review="Optional review")
@app_commands.autocomplete(title=title_autocomplete)
@app_commands.guild_only()
async def rate(
    interaction: discord.Interaction,
    title: str,
    score: app_commands.Range[int, 1, 10],
    review: Optional[app_commands.Range[str, 1, 1000]] = None,
):
    await interaction.response.defer()
    tmdb_id = await resolve_title(title)
    rating = await bot.api.create_rating(
        guild_id=str(interaction.guild_id),
        discord_id=str(interaction.user.id),
        username=interaction.user.display_name,
        tmdb_id=tmdb_id,
        score=score,
        review=review,
    )
    await interaction.followup.send(embed=rating_embed(rating, "Rating saved"))


@bot.tree.command(name="ratings", description="See everyone's ratings and reviews for a movie")
@app_commands.describe(title="Start typing a movie title")
@app_commands.autocomplete(title=title_autocomplete)
@app_commands.guild_only()
async def ratings(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    guild_id = str(interaction.guild_id)
    tmdb_id = await resolve_title(title)
    movie = await bot.api.get_title(tmdb_id, guild_id=guild_id)
    rows = await bot.api.list_ratings(guild_id, tmdb_id=tmdb_id)

    embed = discord.Embed(title=f"Club ratings: {label(movie)}", color=discord.Color.gold())
    if not rows:
        embed.description = "No ratings yet. Be the first with `/rate`."
    else:
        club = movie["club_rating"]
        lines = [f"**Average: {club['average']}/10** from {club['count']} rating(s)\n"]
        for r in rows:
            line = f"**{r['username']}**: {r['score']}/10"
            if r.get("review"):
                review = r["review"]
                line += f"\n> {review[:150]}{'...' if len(review) > 150 else ''}"
            lines.append(line)
        embed.description = "\n".join(lines)[:4000]
    if movie.get("poster_url"):
        embed.set_thumbnail(url=movie["poster_url"])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="myratings", description="See the movies you've rated in this server")
@app_commands.guild_only()
async def myratings(interaction: discord.Interaction):
    await interaction.response.defer()
    rows = await bot.api.list_ratings(
        str(interaction.guild_id), discord_id=str(interaction.user.id), limit=15
    )
    embed = discord.Embed(
        title=f"{interaction.user.display_name}'s ratings", color=discord.Color.gold()
    )
    embed.description = (
        "\n".join(f"**{label(r)}**: {r['score']}/10" for r in rows)
        if rows
        else "You haven't rated anything yet. Try `/rate`."
    )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="editrating", description="Change your score or review for a movie")
@app_commands.describe(title="Start typing a movie title", score="New score, 1 to 10", review="New review")
@app_commands.autocomplete(title=title_autocomplete)
@app_commands.guild_only()
async def editrating(
    interaction: discord.Interaction,
    title: str,
    score: Optional[app_commands.Range[int, 1, 10]] = None,
    review: Optional[app_commands.Range[str, 1, 1000]] = None,
):
    await interaction.response.defer()
    if score is None and review is None:
        raise APIError(400, "Give a new score, a new review, or both.")
    mine = await find_my_rating(interaction, title)
    changes = {"discord_id": str(interaction.user.id)}
    if score is not None:
        changes["score"] = score
    if review is not None:
        changes["review"] = review
    updated = await bot.api.update_rating(mine["id"], **changes)
    await interaction.followup.send(embed=rating_embed(updated, "Rating updated"))


@bot.tree.command(name="deleterating", description="Delete your rating for a movie")
@app_commands.describe(title="Start typing a movie title")
@app_commands.autocomplete(title=title_autocomplete)
@app_commands.guild_only()
async def deleterating(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    mine = await find_my_rating(interaction, title)
    await bot.api.delete_rating(mine["id"], str(interaction.user.id))
    await interaction.followup.send(f"Deleted your rating for **{label(mine)}**.")


async def find_my_rating(interaction: discord.Interaction, title: str) -> dict:
    tmdb_id = await resolve_title(title)
    rows = await bot.api.list_ratings(
        str(interaction.guild_id), tmdb_id=tmdb_id, discord_id=str(interaction.user.id), limit=1
    )
    if not rows:
        raise APIError(404, "You haven't rated that movie yet. Use `/rate` first.")
    return rows[0]


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    if isinstance(original, APIError):
        message = original.detail
    else:
        log.exception("Unhandled command error", exc_info=error)
        message = "Something went wrong on my end. Please try again."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    discord.utils.setup_logging(level=logging.INFO)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
