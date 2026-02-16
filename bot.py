import os
import asyncio
import requests
from bs4 import BeautifulSoup
import discord

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()

async def scan_leboncoin(channel):
    url = "https://www.leboncoin.fr/recherche?text=iphone"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(url, headers=headers)

    if r.status_code != 200:
        print("Erreur Leboncoin")
        return

    soup = BeautifulSoup(r.text, "html.parser")

    ads = soup.find_all("a", href=True)

    count = 0

    for ad in ads:
        text = ad.get_text().strip()

        if "iphone" in text.lower() and len(text) > 10:
            if text in seen:
                continue

            seen.add(text)
            await channel.send(f"📱 {text}")
            count += 1

        if count >= 3:  # MODE DEBUG : max 3 annonces
            break


@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("🚀 SCAN LEBONCOIN LANCÉ")

    while True:
        await scan_leboncoin(channel)
        await asyncio.sleep(60)


client.run(TOKEN)
