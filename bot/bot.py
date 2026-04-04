"""Discord bot with slash commands for managing monitored products."""

import asyncio
import logging
import re

import discord
import httpx
from discord import app_commands
from discord.ext import commands

from config import settings
from monitor.scraper import fetch_product
from monitor.state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOL_URL_PATTERN = re.compile(r"bol\.com/nl/nl/p/[^/]+/(\d{10,})/")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

state: StateManager | None = None


@bot.event
async def on_ready():
    global state
    state = await StateManager.create()
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync commands")
    logger.info("Bot ready as %s", bot.user)


# ---------------------------------------------------------------------------
# /monitor group
# ---------------------------------------------------------------------------

monitor_group = app_commands.Group(name="monitor", description="Manage monitored products")


@monitor_group.command(name="add", description="Add a bol.com product to monitor")
@app_commands.describe(url="The bol.com product URL")
async def monitor_add(interaction: discord.Interaction, url: str):
    match = BOL_URL_PATTERN.search(url)
    if not match:
        await interaction.response.send_message(
            "Invalid URL. Expected: `https://www.bol.com/nl/nl/p/<slug>/<product_id>/`",
            ephemeral=True,
        )
        return

    product_id = match.group(1)
    await state.add_product(product_id, url)
    await state.promote_discovered(product_id)

    embed = discord.Embed(
        title="Product Added",
        description=f"**ID:** {product_id}\n**URL:** {url}",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)
    logger.info("Added product %s via Discord command", product_id)


@monitor_group.command(name="list", description="List all monitored products")
async def monitor_list(interaction: discord.Interaction):
    products = await state.list_products(active_only=True)

    if not products:
        await interaction.response.send_message("No products are being monitored.", ephemeral=True)
        return

    lines = []
    for p in products:
        avail = p.get("last_availability", "Unknown")
        icon = "\U0001f7e2" if avail == "InStock" else "\U0001f534" if avail == "OutOfStock" else "\u26aa"
        name = p.get("name") or p["product_id"]
        price = f"\u20ac{p['price']}" if p.get("price") else ""
        lines.append(f"{icon} **{name}** {price}\n  ID: `{p['product_id']}`")

    embed = discord.Embed(
        title=f"Monitored Products ({len(products)})",
        description="\n\n".join(lines),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed)


@monitor_group.command(name="remove", description="Remove a product from monitoring")
@app_commands.describe(product_id="The product ID to remove")
async def monitor_remove(interaction: discord.Interaction, product_id: str):
    success = await state.remove_product(product_id)
    if success:
        embed = discord.Embed(
            title="Product Removed",
            description=f"Stopped monitoring `{product_id}`",
            color=discord.Color.orange(),
        )
    else:
        embed = discord.Embed(
            title="Not Found",
            description=f"Product `{product_id}` not found in monitor list",
            color=discord.Color.red(),
        )
    await interaction.response.send_message(embed=embed)
    logger.info("Removed product %s via Discord command", product_id)


@monitor_group.command(name="test", description="Test scraping a bol.com URL without adding it")
@app_commands.describe(url="The bol.com product URL to test")
async def monitor_test(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            data = await fetch_product(client, url)
        embed = discord.Embed(
            title=f"Scrape Result: {data.name or 'Unknown'}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Product ID", value=data.product_id or "N/A", inline=True)
        embed.add_field(name="Price", value=f"\u20ac{data.price}" if data.price else "N/A", inline=True)
        embed.add_field(name="Availability", value=data.availability, inline=True)
        embed.add_field(name="Offer UID", value=data.offer_uid or "N/A", inline=True)
        embed.add_field(name="Revision ID", value=data.revision_id[:12] + "..." if data.revision_id else "N/A", inline=True)
        embed.add_field(name="Latency", value=f"{data.latency_ms}ms", inline=True)
        embed.add_field(name="Seller", value=data.seller or "N/A", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Scrape failed: `{exc}`", ephemeral=True)


bot.tree.add_command(monitor_group)


async def main():
    if not settings.discord_bot_token:
        logger.error("DISCORD_BOT_TOKEN not set - bot cannot start")
        return

    async with bot:
        await bot.start(settings.discord_bot_token)


if __name__ == "__main__":
    asyncio.run(main())
