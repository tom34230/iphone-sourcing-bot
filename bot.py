import os
import asyncio
import re
import json
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

SCAN_INTERVAL = 30  # secondes

# DEBUG: envoie 5 annonces même si hors fourchette (juste pour prouver que ça sort bien des iPhones)
DEBUG = True
DEBUG_SEND = 5

# ===== TES FOURCHETTES ACHAT (min/max) =====
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

# ===== EXCLUSIONS ACCESSOIRES =====
BANNED_WORDS = [
    "coque", "housse", "étui", "verre trempé", "film", "protection",
    "chargeur", "câble", "adaptateur", "support",
    "airpods", "écouteurs", "casque",
    "apple watch", "watch", "bracelet",
    "ipad", "macbook"
]

# ===== Détection modèle robuste (gère "iphone15", "15 promax", etc.) =====
MODEL_REGEX = re.compile(r"\biphone\s*([0-9]{2})\b", re.IGNORECASE)

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def detect_model(title: str) -> str | None:
    t = normalize(title)

    # quick reject si pas iphone
    if "iphone" not in t:
        return None

    # détecter génération
    m = MODEL_REGEX.search(t.replace("iphone", "iphone "))
    if not m:
        return None
    gen = m.group(1)
    if gen not in ("13", "14", "15", "16"):
        return None

    # variantes
    is_pro = " pro" in t or "pro " in t or " pro" in t.replace("promax", "pro max")
    is_max = " max" in t or "pro max" in t or "promax" in t
    is_plus = " plus" in t
    is_mini = " mini" in t

    # ordre logique
    if gen == "13" and is_mini:
        return "iphone 13 mini"
    if is_pro and is_max:
        return f"iphone {gen} pro max"
    if is_pro:
        return f"iphone {gen} pro"
    if is_plus:
        return f"iphone {gen} plus"
    if " max" in t and gen in ("13","14","15","16"):
        # au cas où "max" sans "pro"
        return f"iphone {gen} max"
    return f"iphone {gen}"

def is_accessory(title: str) -> bool:
    t = normalize(title)
    return any(w in t for w in BANNED_WORDS)

def parse_price_eur(price_str: str) -> int | None:
    if not price_str:
        return None
    # Vinted renvoie souvent "123" ou "123.00" ou "123,00"
    try:
        return int(float(str(price_str).replace(",", ".")))
    except:
        return None


intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()

async def send_embed(channel, source, model, title, price, url, image_url, min_p=None, max_p=None, debug=False):
    tag = "🧪 DEBUG" if debug else "✅ DEAL"
    rng = "N/A" if (min_p is None or max_p is None) else f"{min_p}€ → {max_p}€"

    embed = discord.Embed(
        title=f"{tag} — {model.upper()} — {price}€",
        description=f"🎯 Fourchette achat : **{rng}**\n🔗 {url}",
        color=0x00ff00 if (min_p is not None and max_p is not None and min_p <= price <= max_p) else 0xf1c40f
    )
    embed.add_field(name="Titre", value=title[:240], inline=False)
    embed.add_field(name="Source", value=source, inline=True)
    if image_url:
        embed.set_image(url=image_url)

    msg = await channel.send(embed=embed)
    for r in ["👀", "💬", "❌", "🔥"]:
        try:
            await msg.add_reaction(r)
        except:
            pass


async def fetch_vinted_json_via_playwright(page):
    """
    On ouvre Vinted en navigateur (anti-403), puis on appelle l'API depuis le contexte navigateur.
    """
    await page.goto("https://www.vinted.fr", wait_until="domcontentloaded", timeout=60000)

    # Cookies (si popup)
    for txt in ["Tout accepter", "Accepter", "J'accepte", "OK"]:
        btn = page.get_by_role("button", name=txt)
        if await btn.count() > 0:
            try:
                await btn.first.click(timeout=2000)
                break
            except:
                pass

    api_url = (
        "https://www.vinted.fr/api/v2/catalog/items"
        "?search_text=iphone"
        "&order=newest_first"
        "&per_page=40"
        "&page=1"
    )

    resp = await page.request.get(api_url)
    status = resp.status
    text = await resp.text()
    return status, text


async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("✅ Scan Vinted (API via navigateur) démarré")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        while not client.is_closed():
            try:
                status, txt = await fetch_vinted_json_via_playwright(page)
                if status != 200:
                    print(f"[VINTED] status={status} (bloqué ?)")
                    await asyncio.sleep(SCAN_INTERVAL)
                    continue

                data = json.loads(txt)
                items = data.get("items", []) or []
                print(f"[SCAN] items API: {len(items)}")

                debug_sent = 0
                deals_sent = 0

                for it in items:
                    item_id = it.get("id")
                    if not item_id:
                        continue
                    key = f"vinted:{item_id}"
                    if key in seen:
                        continue

                    title = it.get("title") or ""
                    if not title:
                        continue

                    # filtre accessoires
                    if is_accessory(title):
                        continue

                    model = detect_model(title)
                    if not model:
                        continue

                    # prix
                    price = parse_price_eur(it.get("price"))
                    if price is None:
                        continue

                    # lien
                    url = it.get("url")
                    if url and url.startswith("/"):
                        url = "https://www.vinted.fr" + url
                    if not url:
                        url = f"https://www.vinted.fr/items/{item_id}"

                    # image
                    image_url = None
                    photos = it.get("photos") or []
                    if photos:
                        p0 = photos[0]
                        image_url = p0.get("full_size_url") or p0.get("high_resolution_url") or p0.get("url")

                    min_p, max_p = BUY_RANGES.get(model, (None, None))

                    # DEBUG: on envoie quelques annonces même hors fourchette
                    if DEBUG and debug_sent < DEBUG_SEND:
                        seen.add(key)
                        await send_embed(channel, "Vinted", model, title, price, url, image_url, min_p, max_p, debug=True)
                        debug_sent += 1
                        continue

                    # Mode normal: uniquement dans ta fourchette
                    if min_p is None or max_p is None:
                        continue
                    if not (min_p <= price <= max_p):
                        continue

                    seen.add(key)
                    await send_embed(channel, "Vinted", model, title, price, url, image_url, min_p, max_p, debug=False)
                    deals_sent += 1

                print(f"[SCAN] debug_sent={debug_sent} deals_sent={deals_sent}")

            except Exception as e:
                print("[SCAN] erreur:", repr(e))

            await asyncio.sleep(SCAN_INTERVAL)


@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())


client.run(TOKEN)
