import requests, json, random, datetime
from bs4 import BeautifulSoup
from email.message import EmailMessage
import smtplib
import os

# ================= CONFIG =================
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]
STATE_FILE = "state.json"
USER_AGENTS_FILE = "user_agents.txt"
ROLLING_WINDOW = 50  # Keep last 50 prices per site
RESET_HOURS = 24     # Partial reset window
# =========================================

def get_headers():
    ua = random.choice(open("user_agents.txt").read().splitlines())
    return {"User-Agent": ua}

def fetch(url):
    return requests.get(url, headers=get_headers(), timeout=20)

def parse_price(price_str):
    """
    Convert price string to float.
    Removes currency symbols, commas, spaces.
    Returns None if conversion fails.
    """
    if not price_str:
        return None
    # Remove anything that's not a digit or dot
    cleaned = "".join(c for c in price_str if c.isdigit() or c == ".")
    try:
        return float(cleaned)
    except:
        return None

# ---------- SITE PARSERS ----------

def parse_amazon(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    price_tag = soup.select_one("span.a-offscreen")
    price = parse_price(price_tag.text) if price_tag else None
    in_stock = soup.find(id="add-to-cart-button") is not None
    return in_stock, price

def parse_overclockers(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    price_tag = soup.select_one(".price, .incvat")
    price = parse_price(price_tag.text) if price_tag else None
    in_stock = "In Stock" in soup.text
    return in_stock, price

def parse_newegg(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    strong = soup.select_one(".price-current strong")
    sup = soup.select_one(".price-current sup")
    price_str = f"{strong.text}{sup.text}" if strong and sup else None
    price = parse_price(price_str)
    in_stock = soup.find("button", string=lambda x: x and "Add to cart" in x) is not None
    return in_stock, price

def parse_paradigit(url):
    soup = BeautifulSoup(fetch(url).text, "html.parser")
    excl = soup.find("div", class_="productdetail_product_exclvat")
    if excl:
        excl.decompose()   # deletes that div and its contents[web:12][web:15]
    meta = soup.find("div", class_="productdetail_product_inclvat")
    price = parse_price(meta.get_text(strip=True)) if meta else None
    in_stock = "Add To Basket" in soup.text or "In stock" in soup.text
    return in_stock, price

# ---------- NOTIFICATIONS ----------

def send_discord(product, price, history):
    recent = history[-5:]
    history_text = "\n".join(
        f"{h['date']} → {product['currency']} {h['price']}"
        for h in recent
    ) or "No history"

    embed = {
        "title": f"🛒 {product_name} — {site.upper()}",
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

def send_email(message):
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_FROM
    msg.set_content(message)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASSWORD)
        smtp.send_message(msg)

# ---------- MAIN ----------

def main():
     # Load or initialize state
    if os.path.exists(STATE_FILE):
        state = json.load(open(STATE_FILE))
    else:
        state = {}

    now = datetime.datetime.utcnow()
    last_reset_str = state.get("last_reset")
    reset_needed = True
    if last_reset_str:
        try:
            last_reset = datetime.datetime.fromisoformat(last_reset_str)
            delta = now - last_reset
            if delta.total_seconds() < RESET_HOURS * 3600:
                reset_needed = False
        except:
            reset_needed = True

    if reset_needed:
        print("Partial reset: clearing old price data older than 24h")
        # Keep only last 24h of price entries
        for product_id in state:
            if product_id == "last_reset":
                continue
            for site in state[product_id]:
                prices = state[product_id][site].get("prices", [])
                new_prices = [
                    p for p in prices
                    if datetime.datetime.fromisoformat(p["date"]) > now - datetime.timedelta(hours=RESET_HOURS)
                ]
                state[product_id][site]["prices"] = new_prices
        state["last_reset"] = now.isoformat()

    
    # 1️⃣ Load data
    products = json.load(open("products.json"))

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

                send_email(
                    f"{product['name']} ({site_name}) IN STOCK\n"
                    f"{currency} {price}\n{url}"
                )

            site_state["in_stock"] = in_stock

     # Save state
    if "last_reset" not in state:
        state["last_reset"] = now.isoformat()
    json.dump(state, open(STATE_FILE, "w"), indent=2)

if __name__ == "__main__":
    main()

