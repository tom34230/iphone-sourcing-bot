import os
import asyncio
import re
import time
import json
import requests
import discord

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

# ===== CONFIG =====
SCAN_INTERVAL = 45  # secondes (évite de spam / limiter les blocages)
TIMEOUT = 15
BATTERY_COST = 15  # € toujours ajouté

# Mets ici tes mots-clés de recherche (tu peux en ajouter)
SEARCH_TERMS = [
    "iphone 13",
    "iphone 13 pro",
    "iphone 14",
    "iphone 14 pro",
    "iphone 15",
    "iphone 15 pro",
    "iphone 16",
    "iphone 16 pro",
]

# Prix de revente (validés)
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

# ===== Discord client =====
intents = discord.Intents.default()
client = discord.Client(intents=intents)

# ===== Seen ads persistence =====
SEEN_FILE = "/tmp/seen_ads.json"
seen_ads = set()

def load_seen():
    global seen_ads
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            seen_ads = set(json.load(f))
    except Exception:
        seen_ads = set()

def save_seen():
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_ads), f)
    except Exception:
        pass

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()

def extract_model(title: str):
    t = normalize(title)
    # IMPORTANT: tester les modèles les + longs d'abord ("pro max" avant "pro", etc.)
    for model in sorted(RESELL_PRICES.keys(), key=len, reverse=True):
        if model in t:
            return model
    return None

def calculate_targets(model: str):
    resell = RESELL_PRICES.get(model)
    part = PART_COST.get(model, 0)
    if not resell:
        return None, None
    cost_base = part + BATTERY_COST
    target_fire = resell - 120 - cost_base
    target_ok = resell - 70 - cost_base
    return max(target_fire, 0), max(target_ok, 0)

async def send_alert(channel, source, title, price, link):
    model = extract_model(title)
    if not model:
        return

    target_fire, target_ok = calculate_targets(model)
    if target_ok is None:
        return

    # On alerte seulement si c'est intéressant (≤ prix cible OK)
    if price > target_ok:
        return

    badge = "🔥" if price <= target_fire else "✅"

    embed = discord.Embed(
        title=f"{badge} {title}",
        description=(
            f"📍 Source : **{source}**\n"
            f"💰 Prix : **{price}€**\n"
            f"🔥 Prix cible (≥120€ marge) : **{target_fire}€**\n"
            f"✅ Prix cible (≥70€ marge) : **{target_ok}€**"
        ),
    )
    embed.add_field(name="Lien", value=link, inline=False)

    msg = await channel.send(embed=embed)
    await msg.add_reaction("👀")
    await msg.add_reaction("💬")
    await msg.add_reaction("❌")
    await msg.add_reaction("🔥")

def http_get(url, headers=None):
    h = {
        "User-Agent": "Mozilla/5.0 (compatible; iPhoneSourcingBot/1.0)",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    }
    if headers:
        h.update(headers)
    return requests.get(url, headers=h, timeout=TIMEOUT)

def scan_vinted(term: str):
    """
    API non-officielle utilisée par le site web Vinted.
    Peut changer. Si ça casse, on adaptera.
    """
    # Exemple France : vinted.fr
    url = (
        "https://www.vinted.fr/api/v2/catalog/items"
        f"?search_text={requests.utils.quote(term)}"
        "&order=newest_first"
        "&per_page=20"
    )
    r = http_get(url)
    if r.status_code != 200:
        return []

    data = r.json()
    items = data.get("items", []) or []
    results = []

    for it in items:
        title = it.get("title") or ""
        price_str = (it.get("price") or "").replace(",", ".")
        try:
            price = int(float(price_str))
        except Exception:
            continue

        item_id = it.get("id")
        if not item_id:
            continue

        link = it.get("url")
        if link and link.startswith("/"):
            link = "https://www.vinted.fr" + link

        results.append({
            "key": f"vinted:{item_id}",
            "title": title,
            "price": price,
            "link": link or "https://www.vinted.fr",
            "source": "Vinted",
        })

    return results

def scan_leboncoin(term: str):
    """
    Leboncoin est plus pénible (beaucoup de contenu est rendu côté client).
    On tente une recherche simple via la page HTML.
    Si ça ne sort rien/403, on basculera sur une autre méthode.
    """
    url = f"https://www.leboncoin.fr/recherche?text={requests.utils.quote(term)}&sort=time"
    r = http_get(url, headers={"Accept": "text/html"})
    if r.status_code != 200:
        return []

    html = r.text

    # Leboncoin embed souvent du JSON dans la page (varie selon versions).
    # On récupère tous les IDs d'annonces et on essaie d'extraire prix + titre.
    # (si ça ne marche pas, on adaptera sur tes logs Railway)
    results = []

    # Tentative simple: repérer des occurrences type "ad_id":123
    ids = set(re.findall(r'"ad_id"\s*:\s*(\d+)', html))
    # fallback (parfois "list_id")
    if not ids:
        ids = set(re.findall(r'"list_id"\s*:\s*(\d+)', html))

    # Sans JSON clair, on ne spam pas: on renvoie vide plutôt que n'importe quoi.
    if not ids:
        return []

    # On crée des résultats minimalistes (titre/prix parfois non extractibles du HTML)
    # -> pour la V1, on se contente du lien, puis on améliorera si besoin.
    for ad_id in list(ids)[:15]:
        results.append({
            "key": f"lbc:{ad_id}",
            "title": f"Annonce Leboncoin #{ad_id} (terme: {term})",
            "price": 999999,  # inconnu => filtré par send_alert car trop cher
            "link": f"https://www.leboncoin.fr/ad/{ad_id}",
            "source": "Leboncoin",
        })

    return results

async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    load_seen()
    await channel.send("✅ BOT OPÉRATIONNEL — scan démarré.")

    while not client.is_closed():
        try:
            found = []

            for term in SEARCH_TERMS:
                # Vinted (fonctionne souvent direct)
                found.extend(scan_vinted(term))

                # Leboncoin (peut nécessiter ajustements)
                found.extend(scan_leboncoin(term))

            new_count = 0

            for ad in found:
                key = ad["key"]
                if key in seen_ads:
                    continue

                seen_ads.add(key)
                new_count += 1

                # Important: Leboncoin V1 met price "inconnu" => pas d'alert
                await send_alert(
                    channel,
                    ad["source"],
                    ad["title"],
                    ad["price"],
                    ad["link"],
                )

            if new_count:
                save_seen()

            # Petit heartbeat discret dans les logs Railway
            print(f"[SCAN] ok — nouveaux éléments: {new_count}")

        except Exception as e:
            print("[SCAN] erreur:", repr(e))

        await asyncio.sleep(SCAN_INTERVAL)

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")

    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("✅ BOT OPÉRATIONNEL — je parle bien dans CE salon.")

    client.loop.create_task(scan_loop())


client.run(TOKEN)
