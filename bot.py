import os
import asyncio
import re
import discord
from playwright.async_api import async_playwright

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

VINTED_URL = "https://www.vinted.fr/catalog?search_text=iphone"

SCAN_INTERVAL = 30
DEBUG_FIRST_N = 3

intents = discord.Intents.default()
client = discord.Client(intents=intents)

seen = set()

def extract_price(text):
    match = re.search(r'(\d+)[.,]?\d*\s?€', text)
    if match:
        return int(match.group(1))
    return None

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

    # Attendre que des annonces apparaissent
    try:
        await page.wait_for_selector('a[href*="/items/"]', timeout=15000)
    except:
        pass

    await page.wait_for_timeout(2000)

    links = await page.query_selector_all('a[href*="/items/"]')
    items = []

    for a in links[:50]:
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

        price = extract_price(txt)
        if price is None:
            continue

        title = txt.split("\n")[0][:120]

        img = None
        img_el = await card.query_selector("img")
        if img_el:
            img = await img_el.get_attribute("src")

        items.append({
            "key": href,
            "title": title,
            "price": price,
            "url": href,
            "img": img
        })

    return items

async def send_alert(channel, item):
    embed = discord.Embed(
        title=f"{item['title']} — {item['price']}€",
        url=item["url"],
        color=0x00ff00
    )

    if item["img"]:
        embed.set_image(url=item["img"])

    await channel.send(embed=embed)

async def scan_loop():
    await client.wait_until_ready()
    channel = await client.fetch_channel(CHANNEL_ID)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("✅ Scan démarré (Vinted via navigateur)")

        while not client.is_closed():
            try:
                items = await fetch_vinted_items(page)
                sent = 0

                for item in items[:DEBUG_FIRST_N]:
                    await send_alert(channel, item)
                    seen.add(item["key"])
                    sent += 1

                print(f"[SCAN] items: {len(items)} — envoyés: {sent}")

            except Exception as e:
                print("[SCAN] erreur:", e)

            await asyncio.sleep(SCAN_INTERVAL)

@client.event
async def on_ready():
    print(f"Bot connecté en tant que {client.user}")
    client.loop.create_task(scan_loop())

client.run(TOKEN)
