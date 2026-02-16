import os
import asyncio
import re
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# ===== CONFIG =====
SCAN_INTERVAL = 30  # secondes

# DEBUG: envoie 10 annonces iPhone (même hors fourchette) pour valider que ça scrape bien
DEBUG = True
DEBUG_SEND = 10

# Recherche Vinted (newest first)
VINTED_URL = "https://www.vinted.fr/catalog?search_text=iphone&order=newest_first"

# ===== PRIX D'ACHAT (TES FOURCHETTES) =====
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

# Accessoires à exclure
BANNED_WORDS = [
    "coque", "housse", "étui", "verre", "film", "protection",
    "chargeur", "câble", "adaptateur", "support", "dock",
    "airpods", "écouteurs", "casque",
    "apple watch", "watch", "bracelet",
    "ipad", "macbook"
]

# Regex robuste pour détecter iPhone 13-16 + variantes
MODEL_REGEX = re.compile(
    r"\biphone\s*(13|14|15|16)\s*(mini|plus|pro|max|pro\s*max)?\b",
    re.IGNORECASE
)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()


def extract_price(text: str):
    # "100 €" ou "100,00 €"
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*€", text)
    if not m:
        return None
    return int(float(m.group(1).replace(",", ".")))


def normalize_model(match: re.Match):
    num = match.group(1)
    var = (match.group(2) or "").lower().strip()
    var = var.replace("  ", " ").replace("promax", "pro max")
    if var == "pro max":
        return f"iphone {num} pro max"
    if var in ("mini", "plus", "pro", "max"):
        return f"iphone {num} {var}"
    return f"iphone {num}"


async def fetch_vinted_items(page):
    await page.goto(VINTED_URL, wait_until="domcontentloaded", timeout=60000)

    # Accepter cookies si présents
    for txt in ["Tout accepter", "Accepter", "J'accepte", "OK"]:
        btn = page.get_by_role("button", name=txt)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=2000)
                break
            except:
                pass

    # Attendre les annonces
    try:
        await page.wait_for_selector('a[href*="/items/"]', timeout=15000)
    except:
        pass

    await page.wait_for_timeout(1500)

    links = await page.query_selector_all('a[href*="/items/"]')
    items = []

    for a in links[:120]:
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
        if any(w in lower for w in BANNED_WORDS):
            continue

        # Garder uniquement iPhone 13 -> 16
        m = MODEL_REGEX.search(lower)
        if not m:
            continue

        model = normalize_model(m)

        price = extract_price(txt)
        if price is None:
            continue

        # Filtre fourchette (désactivé en DEBUG)
        min_p, max_p = BUY_RANGES.get(model, (None, None))
        if (not DEBUG) and (min_p is not None) and (not (min_p <= price <= max_p)):
            continue

        img = None
        img_el = await card.query_selector("img")
        if img_el:
            img = await img_el.get_attribute("src")

        # Titre plus propre
        first_line = txt.split("\n")[0][:90]

        items.append({
            "key": href,
            "model": model,
            "title": first_line,
            "price": price,
            "url": href,
            "img": img,
            "min": min_p,
            "max": max_p
        })

    return items


async def send_alert(channel, item):
    model = item["model"]
    price = item["price"]
    url = item["url"]
    img = item["img"]
    min_p = item["min"]
    max_p = item["max"]

    # Label debug
    tag = "🧪 DEBUG" if DEBUG else "✅ DEAL"

    # Fourchette affichée (si connue)
    range_txt = f"{min_p}€ → {max_p}€" if (min_p is not None and max_p is not None) else "N/A"

    embed = discord.Embed(
        title=f"{tag} — {model.upper()} — {price}€",
        description=f"🎯 Fourchette achat : **{range_txt}**\n🔗 {url}",
        color=0x00ff00 if (min_p is not None and max_p is not None and min_p <= price <= max_p) else 0xf1c40f
    )

    embed.add_field(name="Titre annonce", value=item["title"], inline=False)

    if img:
        embed.set_image(url=img)

    await channel.send(embed=embed)


async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    await channel.send("✅ Scan démarré (Vinted via navigateur)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        while not client.is_closed():
            try:
                items = await fetch_vinted_items(page)

                sent = 0
                for it in items:
                    await send_alert(channel, it)
                    seen.add(it["key"])
                    sent += 1

                    # En DEBUG on limite à 10 messages / cycle
                    if DEBUG and sent >= DEBUG_SEND:
                        break

                print(f"[SCAN] items filtrés: {len(items)} — envoyés: {sent}")

            except Exception as e:
                print("[SCAN] erreur:", repr(e))

            await asyncio.sleep(SCAN_INTERVAL)


@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())


client.run(TOKEN)
