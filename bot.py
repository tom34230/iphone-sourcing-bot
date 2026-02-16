import os
import asyncio
import time
import re
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "30"))  # secondes
DEBUG_FIRST_N = int(os.getenv("DEBUG_FIRST_N", "3"))   # envoie 3 annonces au début

# Recherche Vinted (newest first)
VINTED_URL = (
    "https://www.vinted.fr/catalog"
    "?search_text=iphone"
    "&order=newest_first"
)

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()
debug_sent = 0


def extract_price(text: str):
    # Ex: "100,00 €" ou "100 €"
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)\s*€", text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


async def send_item(channel, title, price, url, img=None, source="VINTED"):
    embed = discord.Embed(
        title=f"[{source}] {title}",
        description=f"💰 {price} €\n🔗 {url}",
    )
    if img:
        embed.set_thumbnail(url=img)
    await channel.send(embed=embed)


async def fetch_vinted_items(page):
    # Charge la page
    await page.goto(VINTED_URL, wait_until="domcontentloaded", timeout=60000)
    # Un petit wait pour laisser le temps au rendu
    await page.wait_for_timeout(1500)

    # Vinted change parfois ses classes, donc on prend un sélecteur large :
    # liens contenant /items/
    links = await page.query_selector_all('a[href*="/items/"]')

    items = []
    for a in links:
        href = await a.get_attribute("href")
        if not href:
            continue
        if not href.startswith("http"):
            href = "https://www.vinted.fr" + href

        # On remonte au “bloc” parent pour récupérer titre/prix/image
        card = await a.evaluate_handle("el => el.closest('div')")
        card_text = (await card.inner_text()) if card else ""
        # price dans le texte
        price = extract_price(card_text)
        if price is None:
            continue

        # title = on prend une ligne “raisonnable”
        title = card_text.strip().split("\n")[0][:120] if card_text else "Annonce Vinted"

        # image
        img = None
        if card:
            img_el = await card.query_selector("img")
            if img_el:
                img = await img_el.get_attribute("src")

        key = href
        items.append({"key": key, "title": title, "price": price, "url": href, "img": img})

    # Dé-doublonnage (Vinted peut répéter)
    uniq = {}
    for it in items:
        uniq[it["key"]] = it
    return list(uniq.values())


async def scan_loop():
    global debug_sent

    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    # Playwright (headless)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        await channel.send("✅ Scan démarré (Vinted via navigateur)")

        while not client.is_closed():
            try:
                items = await fetch_vinted_items(page)

                sent_now = 0
                for it in items:
                    if it["key"] in seen:
                        continue

                    # Mode DEBUG : on force l’envoi des 3 premières annonces trouvées
                    if debug_sent < DEBUG_FIRST_N:
                        seen.add(it["key"])
                        await send_item(channel, it["title"], it["price"], it["url"], it["img"], source="VINTED DEBUG")
                        debug_sent += 1
                        sent_now += 1
                        continue

                    # Mode normal : ici tu peux filtrer plus tard (prix cible etc.)
                    # Pour l’instant on envoie tout ce qui est nouveau (sinon tu vas encore croire “ça marche pas”)
                    seen.add(it["key"])
                    await send_item(channel, it["title"], it["price"], it["url"], it["img"], source="VINTED")
                    sent_now += 1

                print(f"[SCAN] ok — items: {len(items)} — envoyés: {sent_now}")

            except Exception as e:
                print("[SCAN] erreur:", repr(e))

            await asyncio.sleep(SCAN_INTERVAL)


@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())


client.run(TOKEN)
