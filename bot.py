import os
import asyncio
import requests
import discord

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()

SEARCH_TERMS = ["iphone 13", "iphone 14", "iphone 15", "iphone 16"]

def scan_vinted(term: str):
    url = (
        "https://www.vinted.fr/api/v2/catalog/items"
        f"?search_text={requests.utils.quote(term)}"
        "&order=newest_first"
        "&per_page=10"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }

    r = requests.get(url, headers=headers, timeout=15)
    print("[VINTED] status:", r.status_code, "len:", len(r.text))

    if r.status_code != 200:
        return []

    data = r.json()
    items = data.get("items", []) or []
    print("[VINTED] items:", len(items))

    results = []
    for it in items:
        item_id = it.get("id")
        title = it.get("title") or ""
        price_str = (it.get("price") or "").replace(",", ".")
        try:
            price = int(float(price_str))
        except Exception:
            continue

        link = it.get("url")
        if link and link.startswith("/"):
            link = "https://www.vinted.fr" + link

        results.append((f"vinted:{item_id}", title, price, link or "https://www.vinted.fr"))

    return results

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    channel = await client.fetch_channel(CHANNEL_ID)
    await channel.send("✅ BOT OPÉRATIONNEL — scan Vinted démarré.")

    while True:
        try:
            sent = 0
            for term in SEARCH_TERMS:
                for key, title, price, link in scan_vinted(term):
                    if key in seen:
                        continue
                    seen.add(key)

                    await channel.send(f"🆕 VINTED | {title} | {price}€\n{link}")
                    sent += 1

                    if sent >= 5:  # debug: max 5 messages par cycle
                        break
                if sent >= 5:
                    break

            print("[SCAN] cycle ok — envoyés:", sent)

        except Exception as e:
            print("[SCAN] erreur:", repr(e))

        await asyncio.sleep(60)

client.run(TOKEN)
