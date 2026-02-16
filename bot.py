import os
import asyncio
import re
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

SCAN_INTERVAL = 30

# ===== PRIX D'ACHAT QUE TU M'AS DONNÉS =====

BUY_RANGES = {
    "iphone 13 mini": (50, 120),
    "iphone 13": (50, 130),
    "iphone 13 pro": (80, 200),
    "iphone 13 pro max": (80, 220),

    "iphone 14": (90, 200),
    "iphone 14 plus": (90, 250),
    "iphone 14 pro": (90, 320),
    "iphone 14 pro max": (90, 330),

    "iphone 15": (90, 350),
    "iphone 15 plus": (90, 450),
    "iphone 15 pro": (90, 480),
    "iphone 15 pro max": (90, 550),

    "iphone 16": (190, 450),
    "iphone 16 plus": (190, 500),
    "iphone 16 pro": (190, 550),
    "iphone 16 pro max": (190, 600),
}

VINTED_URL = "https://www.vinted.fr/catalog?search_text=iphone&order=newest_first"

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()

def extract_price(text):
    match = re.search(r'(\d+)[.,]?\d*\s?€', text)
    if match:
        return int(match.group(1))
    return None

def detect_model(text):
    text = text.lower()
    for model in BUY_RANGES.keys():
        if model in text:
            return model
    return None

async def fetch_vinted_items(page):
    await page.goto(VINTED_URL, wait_until="domcontentloaded", timeout=60000)

    # Accepter cookies si besoin
    for txt in ["Tout accepter", "Accepter", "J'accepte", "OK"]:
        btn = page.get_by_role("button", name=txt)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=2000)
                break
            except:
                pass

    await page.wait_for_selector('a[href*="/items/"]', timeout=15000)
    await page.wait_for_timeout(1500)

    links = await page.query_selector_all('a[href*="/items/"]')
    items = []

    banned_words = [
        "coque", "housse", "étui", "verre", "film", "chargeur",
        "airpods", "watch", "bracelet", "ipad", "macbook"
    ]

    for a in links[:80]:
        href = await a.get_attribute("href")
        if not href:
            continue
        if not href.startswith("http"):
            href = "https://www.vinted.fr" + href

        if href in seen:
            continue

        card = await a.evaluate_handle("el => el.closest('article') || el.closest('div')")
        if not card:
            continue

        txt = (await card.inner_text()).strip()
        if not txt:
            continue

        lower = txt.lower()

        # Exclure accessoires
        if any(word in lower for word in banned_words):
            continue

        model = detect_model(lower)
        if not model:
            continue

        price = extract_price(txt)
        if price is None:
            continue

        min_price, max_price = BUY_RANGES[model]

        # Filtre selon TES prix d'achat
        if not (min_price <= price <= max_price):
            continue

        img = None
        img_el = await card.query_selector("img")
        if img_el:
            img = await img_el.get_attribute("src")

        items.append({
            "key": href,
            "model": model,
            "price": price,
            "url": href,
            "img": img
        })

    return items

async def send_alert(channel, item):
    embed = discord.Embed(
        title=f"{item['model'].upper()} — {item['price']}€",
        url=item["url"],
        color=0x00ff00
    )

    if item["img"]:
        embed.set_image(url=item["img"])

    embed.add_field(
        name="🎯 Fourchette d'achat",
        value=f"{BUY_RANGES[item['model']][0]}€ → {BUY_RANGES[item['model']][1]}€",
        inline=False
    )

    await channel.send(embed=embed)

async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("✅ Scan Vinted démarré")

        while not client.is_closed():
            try:
                items = await fetch_vinted_items(page)

                for item in items:
                    await send_alert(channel, item)
                    seen.add(item["key"])

                print(f"[SCAN] Trouvés: {len(items)}")

            except Exception as e:
                print("[SCAN] erreur:", e)

            await asyncio.sleep(SCAN_INTERVAL)

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())

client.run(TOKEN)
