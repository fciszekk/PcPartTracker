import requests, json, random, datetime
from bs4 import BeautifulSoup

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1453085062290477168/rKLmG2mVIkNmzLA9qKjIbYBUYFefxH3VxvkkuECWavBFFDkyEcYgJZ0r3HZte4QHVQ4g"

def get_headers():
    with open("user_agents.txt") as f:
        ua = random.choice(f.read().splitlines())
    return {"User-Agent": ua}

def fetch(url):
    return requests.get(url, headers=get_headers(), timeout=15)

def parse_amazon(url):
    r = fetch(url)
    soup = BeautifulSoup(r.text, "html.parser")

    price_tag = soup.select_one("span.a-offscreen")
    price = float(price_tag.text.replace("£", "").replace(",", "")) if price_tag else None

    in_stock = soup.find(id="add-to-cart-button") is not None
    return in_stock, price

def send_discord(product, price, history, url):
    recent = history[-5:]
    history_text = "\n".join(
        f"{p['date']} → £{p['price']}"
        for p in recent
    ) or "No history yet"

    embed = {
        "title": f"🛒 {product['name']} AVAILABLE",
        "description": f"[Buy Link]({url})",
        "color": 3066993,
        "fields": [
            {"name": "Current Price", "value": f"£{price}", "inline": True},
            {"name": "Target Price", "value": f"£{product['max_price']}", "inline": True},
            {"name": "Price History", "value": history_text[:1024], "inline": False}
        ],
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})

def main():
    products = json.load(open("products.json"))
    state = json.load(open("state.json"))

    for p in products:
        if p["site"] == "amazon":
            in_stock, price = parse_amazon(p["url"])
        else:
            continue

        item = state.setdefault(p["name"], {"in_stock": False, "prices": []})

        if price:
            item["prices"].append({
                "price": price,
                "date": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            })
            item["prices"] = item["prices"][-50:]  # cap history

        if in_stock and price and price <= p["max_price"] and not item["in_stock"]:
            send_discord(p, price, item["prices"], p["url"])

        item["in_stock"] = in_stock

    json.dump(state, open("state.json", "w"), indent=2)

if __name__ == "__main__":
    main()
