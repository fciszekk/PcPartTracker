import requests, json, random, datetime
from bs4 import BeautifulSoup
from email.message import EmailMessage
import smtplib

# ================= CONFIG =================
DISCORD_WEBHOOK = ${{ secrets.DISCORD_WEBHOOK }}
EMAIL_FROM = ${{ secrets.FROM_EMAIL }}
EMAIL_PASSWORD = ${{ secrets.EMAIL_PASSWORD }}
# =========================================

def get_headers():
    ua = random.choice(open("user_agents.txt").read().splitlines())
    return {"User-Agent": ua}

def fetch(url):
    return requests.get(url, headers=get_headers(), timeout=20)

# ---------- SITE PARSERS ----------

def parse_amazon(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    price = soup.select_one("span.a-offscreen")
    price = float(price.text.replace("£","").replace(",","")) if price else None
    in_stock = soup.find(id="add-to-cart-button") is not None
    return in_stock, price

def parse_overclockers(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    price_tag = soup.select_one(".price, .incvat")
    price = float(price_tag.text.replace("£","").replace(",","")) if price_tag else None
    in_stock = "In Stock" in soup.text
    return in_stock, price

def parse_newegg(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    strong = soup.select_one(".price-current strong")
    sup = soup.select_one(".price-current sup")
    price = float(f"{strong.text}{sup.text}") if strong and sup else None
    in_stock = soup.find("button", string=lambda x: x and "Add to cart" in x) is not None
    return in_stock, price

def parse_paradigit(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    meta = soup.find("meta", itemprop="price")
    price = float(meta["content"]) if meta else None
    in_stock = "Op voorraad" in soup.text or "inStock" in soup.text
    return in_stock, price

# ---------- NOTIFICATIONS ----------

def send_discord(product, price, history):
    recent = history[-5:]
    history_text = "\n".join(
        f"{h['date']} → {product['currency']} {h['price']}"
        for h in recent
    ) or "No history"

    embed = {
        "title": f"🛒 {product_name} — {site.upper()}"
        "description": f"[Buy Link]({product['url']})",
        "color": 3066993,
        "fields": [
            {"name": "Price", "value": f"{product['currency']} {price}", "inline": True},
            {"name": "Target", "value": f"{product['currency']} {product['max_price']}", "inline": True},
            {"name": "Price History", "value": history_text[:1024], "inline": False}
        ],
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]})

def send_sms(message):
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_FROM
    msg.set_content(message)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASSWORD)
        smtp.send_message(msg)

# ---------- MAIN ----------

def main():
    # 1️⃣ Load data
    products = json.load(open("products.json"))
    state = json.load(open("state.json"))

    # 2️⃣ Define parsers mapping
    parsers = {
        "amazon": parse_amazon,
        "overclockers": parse_overclockers,
        "newegg": parse_newegg,
        "paradigit": parse_paradigit
    }

    # 3️⃣ ===== HERE is where the product loop goes =====
    for product in products:
        pid = product["id"]
        state.setdefault(pid, {})

        for site in product["sites"]:
            site_name = site["site"]
            url = site["url"]
            currency = site["currency"]

            parser = parsers.get(site_name)
            if not parser:
                continue

            in_stock, price = parser(url)

            site_state = state[pid].setdefault(
                site_name, {"in_stock": False, "prices": []}
            )

            if price:
                site_state["prices"].append({
                    "price": price,
                    "date": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                })
                site_state["prices"] = site_state["prices"][-50:]

            target = product["max_price"].get(currency)

            if (
                in_stock and price and target
                and price <= target
                and not site_state["in_stock"]
            ):
                send_discord(
                    product_name=product["name"],
                    site=site_name,
                    price=price,
                    currency=currency,
                    history=site_state["prices"],
                    url=url
                )

                send_sms(
                    f"{product['name']} ({site_name}) IN STOCK\n"
                    f"{currency} {price}\n{url}"
                )

            site_state["in_stock"] = in_stock

    # 4️⃣ Save state
    json.dump(state, open("state.json", "w"), indent=2)


if __name__ == "__main__":
    main()

