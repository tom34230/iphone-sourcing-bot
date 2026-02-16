import os
import asyncio
import discord

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("✅ BOT OPÉRATIONNEL")

    while True:
        await channel.send("🔍 Test annonce iPhone 14 Pro - 300€")
        await asyncio.sleep(60)

client.run(TOKEN)
