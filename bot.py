import os
import re
import asyncio
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

SCAN_INTERVAL = 20  # secondes (0-20s de "latence" max)
DEBUG_FORCE_FIRST_N = 3  # envoie les 3 premières annonces même si hors cible

# --- Tes prix (garde les tiens) ---
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

BATTERY_COST = 15

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()
debug_sent = 0

def extract_model(text: str):
    t = text.lower()
    # match le plus long d'abord (évite que "iphone 13" prenne "iphone 13 pro")
    for model in sorted(RESELL_PRICES.keys(), key=len, reverse=True):
        if model in t:
            return model
    return None

def calculate_targets(model: str):
    resell = RESELL_PRICES.get(model)
    part = PART_COST.get(model, 0)
    cost_base = part + BATTERY_COST
    target_fire = max(resell - 120 - cost_base, 0)
    target_ok = max(resell - 70 - cost_base, 0)
    return target_fire, target_ok

async def send_vinted_embed(channel, item):
    global debug_sent

    title = item.get("title") or "Annonce Vinted"
    price = item.get("price", 0)
    currency = item.get("currency") or "EUR"
    item_id = item.get("id")
    url = item.get("url")
    if not url and item_id:
        url = f"https://www.vinted.fr/items/{item_id}"

    photos = item.get("photos") or []
    image_url = None
    if photos:
        # meilleure image dispo (souvent 'url' / 'full_size_url' / 'high_resolution_url')
        p0 = photos[0]
        image_url = (
            p0.get("full_size_url")
            or p0.get("high_resolution_url")
            or p0.get("url")
        )

    model = extract_model(title)
    if not model:
        return 0

    target_fire, target_ok = calculate_targets(model)

    # --- Filtre "marge" (sauf DEBUG_FORCE_FIRST_N) ---
    force_send = debug_sent < DEBUG_FORCE_FIRST_N
    if (not force_send) and (price > target_ok):
        return 0

    if force_send:
        debug_sent += 1

    embed = discord.Embed(
        title=title,
        description=(
            f"💰 Prix : **{price} {currency}**\n"
            f"🔥 Cible (≥120€ marge) : **{target_fire}€**\n"
            f"✅ Cible (≥70€ marge) : **{target_ok}€**\n"
            f"📦 Modèle détecté : **{model}**"
        ),
        color=0x2ecc71 if price <= target_ok else 0xf1c40f
    )
    embed.add_field(name="Lien", value=url, inline=False)
    if image_url:
        embed.set_image(url=image_url)

    msg = await channel.send(embed=embed)
    for r in ["👀", "💬", "❌", "🔥"]:
        try:
            await msg.add_reaction(r)
        except:
            pass

    return 1

async def fetch_vinted_items(playwright):
    """
    On utilise un vrai Chromium, on charge la recherche,
    puis on récupère le JSON via l'API interne depuis le contexte navigateur.
    """
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        locale="fr-FR",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
    )
    page = await context.new_page()

    # Page de recherche (tu peux mettre d'autres mots clés)
    search_url = "https://www.vinted.fr/catalog?search_text=iphone"
    await page.goto(search_url, wait_until="domcontentloaded")

    # IMPORTANT: on appelle l'endpoint depuis le navigateur (cookies/headers ok)
    api_url = "https://www.vinted.fr/api/v2/catalog/items?search_text=iphone&per_page=20&page=1"
    resp = await page.request.get(api_url)

    status = resp.status
    text = await resp.text()
    await context.close()
    await browser.close()
    return status, text

async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    await channel.send("✅ Bot Vinted (Playwright) lancé. Scan en cours…")

    async with async_playwright() as p:
        while not client.is_closed():
            try:
                status, text = await fetch_vinted_items(p)
                if status != 200:
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                data = None
                try:
                    data = __import__("json").loads(text)
                except:
                    data = None

                items = []
                if isinstance(data, dict):
                    items = data.get("items") or []

                sent = 0
                for it in items:
                    item_id = it.get("id")
                    if not item_id:
                        continue
                    key = f"vinted:{item_id}"
                    if key in seen:
                        continue
                    seen.add(key)
                    sent += await send_vinted_embed(channel, it)

                print(f"[SCAN] ok — nouveaux: {len(items)} — envoyés: {sent}")
            except Exception as e:
                print("[SCAN] erreur:", e)

            await asyncio.sleep(SCAN_INTERVAL)

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())

client.run(TOKEN)
