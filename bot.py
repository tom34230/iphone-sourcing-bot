import os
import asyncio
import re
import time
import requests
from bs4 import BeautifulSoup
import discord

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# ===== CONFIG =====
SCAN_INTERVAL = 30  # secondes
SOURCES = ["leboncoin", "vinted"]  # extensible plus tard
OLED_DEFAULT = True
BATTERY_COST = 15  # € toujours ajouté

# Prix de revente (ceux que tu as validés)
RESELL_PRICES = {
    "iphone 13 mini": 210,
    "iphone 13": 240,
    "iphone 13 pro": 300,
    "iphone 13 pro max": 350,
    "iphone 14": 330,
    "iphone 14 plus": 350,
    "iphone 14 pro": 430,
    "iphone 14 pro max": 450,
    "iphone 15": 450,
    "iphone 15 plus": 530,
    "iphone 15 pro": 550,
    "iphone 15 pro max": 600,
    "iphone 16": 630,
    "iphone 16 plus": 650,
    "iphone 16 pro": 650,
    "iphone 16 pro max": 700,
}

# Prix pièces (OLED par défaut + batterie toujours)
PART_COST = {
    "iphone 13 mini": 35,
    "iphone 13": 28,
    "iphone 13 pro": 29,
    "iphone 13 pro max": 29,
    "iphone 14": 24,
    "iphone 14 plus": 31,
    "iphone 14 pro": 41,
    "iphone 14 pro max": 40,
    "iphone 15": 41,
    "iphone 15 plus": 41,
    "iphone 15 pro": 42,
    "iphone 15 pro max": 38,
    "iphone 16": 40,
    "iphone 16 plus": 46,
    "iphone 16 pro": 44,
    "iphone 16 pro max": 46,
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen_ads = {}

def extract_model(title):
    t = title.lower()
    for model in RESELL_PRICES.keys():
        if model in t:
            return model
    return None

def extract_price(text):
    match = re.search(r'(\d+)\s?€', text)
    if match:
        return int(match.group(1))
    return None

def calculate_targets(model):
    resell = RESELL_PRICES.get(model)
    part = PART_COST.get(model, 0)
    if not resell:
        return None, None
    # Batterie toujours ajoutée
    cost_base = part + BATTERY_COST
    target_fire = resell - 120 - cost_base
    target_ok = resell - 70 - cost_base
    return max(target_fire, 0), max(target_ok, 0)

async def send_alert(channel, title, price, link):
    model = extract_model(title)
    if not model:
        return

    target_fire, target_ok = calculate_targets(model)

    embed = discord.Embed(
        title=title,
        description=f"💰 Prix : {price}€\n🔥 Prix cible (≥120€ marge) : {target_fire}€\n✅ Prix cible (≥70€ marge) : {target_ok}€",
        color=0x00ff00
    )
    embed.add_field(name="Lien", value=link, inline=False)

    msg = await channel.send(embed=embed)
    await msg.add_reaction("👀")
    await msg.add_reaction("💬")
    await msg.add_reaction("❌")
    await msg.add_reaction("🔥")

async def scan_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    while not client.is_closed():
        await channel.send("🔍 Scan en cours...")
        await asyncio.sleep(30)


@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    
    channel = client.get_channel(CHANNEL_ID)
    await channel.send("✅ BOT OPÉRATIONNEL")
    
    client.loop.create_task(scan_loop())

