from __future__ import annotations

import re
import time
import json
import random
from urllib.parse import quote
import shutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import requests  # add this at the top with other imports
from settings import GOOGLE_MAPS_API_KEY  # add this too
from database import get_airbnb_listings, get_session, save_airbnb_listings

AIRBNB_CACHE_HOURS = 24


def _get_listing_coords(
    driver: webdriver.Chrome,
    listing_url: str,
    fallback_lat: float,
    fallback_lng: float,
) -> tuple[float, float] | None:
    """
    Tries to pull lat/lng from Airbnb's __NEXT_DATA__ blob.
    Returns None if not found (caller handles fallback).
    """
    try:
        driver.get(listing_url)
        time.sleep(2)
        page_src = driver.page_source
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_src, re.S)
        if match:
            data = json.loads(match.group(1))
            listing = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("listing", {})
            )
            lat = listing.get("lat") or listing.get("location", {}).get("lat")
            lng = listing.get("lng") or listing.get("location", {}).get("lng")
            if lat and lng:
                print(f"[coords] Found in __NEXT_DATA__: {lat}, {lng}")
                return float(lat), float(lng)
        print("[coords] __NEXT_DATA__ had no coords")
    except Exception as e:
        print(f"[coords] Exception reading listing page: {e}")
    return None

def _geocode_name(name: str, city: str, country: str) -> tuple[float, float] | None:
    """
    Uses Google Geocoding to find the city centre, then adds jitter so
    multiple listings don't all stack on the same point.
    """
    if not GOOGLE_MAPS_API_KEY:
        return None

    # Just geocode the city — listing names like "Flat in Pattaya" give the
    # same result anyway, so querying the city directly is cleaner
    query = f"{city}, {country}"
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": GOOGLE_MAPS_API_KEY},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if results:
            loc = results[0]["geometry"]["location"]
            # Add jitter (~0–2 km spread) so pins don't overlap
            lat = loc["lat"] + random.uniform(-0.015, 0.015)
            lng = loc["lng"] + random.uniform(-0.015, 0.015)
            print(f"[coords] Geocoded '{name}' → {lat:.5f}, {lng:.5f} (jittered)")
            return lat, lng
    except Exception as e:
        print(f"[coords] Geocoding failed for '{name}': {e}")
    return None

def scrape_airbnb_listings(
    city_name: str,
    country: str,
    destination_id: str | None = None,
    limit: int = 10,
    dest_lat: float = 0.0,
    dest_lng: float = 0.0,
) -> tuple[float | None, list[dict]]:
    """
    Returns (average_nightly_price, list_of_listing_dicts).

    Pass 1: collect all card data WITHOUT navigating away (so cards stay in DOM).
    Pass 2: visit each listing URL to get coordinates.
    """
    dest_id = destination_id or re.sub(r"[^a-z0-9]+", "-", city_name.lower()).strip("-")

    # ── 1. Try DB cache ────────────────────────────────────────────────────────
    db = get_session()
    try:
        cached = get_airbnb_listings(db, dest_id, max_age_hours=AIRBNB_CACHE_HOURS)
        if cached:
            print(f"[airbnb] Returning {len(cached)} cached listings for '{dest_id}'.")
            prices = [r["price_nightly"] for r in cached if r["price_nightly"]]
            avg = round(sum(prices) / len(prices), 2) if prices else None
            return avg, cached
    finally:
        db.close()

    # ── 2. Scrape Airbnb ───────────────────────────────────────────────────────
    query = quote(f"{city_name}, {country}")
    url = f"https://www.airbnb.com/s/{query}/homes"

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if shutil.which("chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
        service = Service("/usr/bin/chromedriver")
    else:
        service = Service(ChromeDriverManager().install())

    listings_data: list[dict] = []
    prices: list[float] = []
    avg_price: float | None = None
    driver: webdriver.Chrome | None = None
    detected_symbol = "£"

    try:
        # Set paths dynamically based on environment
        if shutil.which("chromium"):
            print("[airbnb] Chromium found on system path (Streamlit environment).")
            chrome_options.binary_location = "/usr/bin/chromium"
            service = Service("/usr/bin/chromedriver")
        else:
            print("[airbnb] Chromium not found. Falling back to ChromeDriverManager (Local).")
            service = Service(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=chrome_options)

        print(f"[airbnb] Navigating to: {url}")
        driver.get(url)

        wait = WebDriverWait(driver, 20)
        wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div[data-testid="card-container"]')
            )
        )

        # Scroll aggressively to trigger lazy-loading, stop early if enough cards
        prev_count = 0
        for _ in range(6):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="card-container"]')
            print(f"[airbnb] Cards visible so far: {len(cards)}")
            if len(cards) >= limit:
                break
            if len(cards) == prev_count:
                # No new cards — scroll back up then down to re-trigger
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
            prev_count = len(cards)

        cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="card-container"]')
        print(f"[airbnb] Final card count: {len(cards)} (will parse up to {limit})")

    # ── PASS 1: Read cards incrementally while scrolling down ────────────────────
        # Defeats Airbnb's DOM virtualization by processing cards while active in viewport.
        raw_cards: list[dict] = []
        seen_urls = set()
        scroll_attempts = 0
        max_scroll_attempts = 15

        while len(raw_cards) < limit and scroll_attempts < max_scroll_attempts:
            # Re-find whatever cards are currently active in the DOM tree
            cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="card-container"]')
            
            for card in cards:
                if len(raw_cards) >= limit:
                    break
                
                try:
                    # 1. Grab URL first to use as a unique key descriptor
                    listing_url = None
                    try:
                        link_elem = card.find_element(By.CSS_SELECTOR, 'a[href*="/rooms/"]')
                        href = link_elem.get_attribute("href")
                        listing_url = href if href.startswith("http") else f"https://www.airbnb.com{href}"
                    except Exception:
                        pass

                    # Skip if we already parsed this specific property listing
                    if listing_url and listing_url in seen_urls:
                        continue

                    # 2. Briefly focus the element to force rendering its sub-elements
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                    time.sleep(0.4)

                    card_text = card.text
                    if not card_text or len(card_text.strip()) < 10:
                        time.sleep(0.4) # Give a second chance layout paint
                        card_text = card.text

                    lines = [l.strip() for l in card_text.splitlines() if l.strip()]
                    if not lines:
                        continue

                    # Title Extraction
                    title = "Unknown Listing"
                    try:
                        title_elem = card.find_element(By.CSS_SELECTOR, '[id^="title_"]')
                        title = title_elem.text.strip()
                    except Exception:
                        for line in lines:
                            if (
                                len(line) > 8
                                and not re.match(r"^[\d.£$€,]", line)
                                and "favourite" not in line.lower()
                                and "guest" not in line.lower()
                            ):
                                title = line
                                break

                    # Description Extraction
                    description = None
                    for i, line in enumerate(lines):
                        if line == title and i + 1 < len(lines):
                            candidate = lines[i + 1]
                            if (
                                len(candidate) > 10
                                and not re.match(r"^[\d£$€]", candidate)
                                and "bedroom" not in candidate.lower()
                                and "bath" not in candidate.lower()
                            ):
                                description = candidate
                            break

                    # Bedrooms Extraction
                    bed_parts = []
                    for line in lines:
                        if re.search(r"\d+\s*(bedroom|bed|bathroom|studio)", line, re.I):
                            bed_parts.append(line)
                        if len(bed_parts) == 2:
                            break
                    bedrooms = " · ".join(bed_parts) if bed_parts else None

                    # Price Parsing
                    price_val = None
                    all_prices = re.findall(r"([£$€])([\d,]+)", card_text)
                    if all_prices:
                        detected_symbol = all_prices[0][0]
                        price_val = float(all_prices[0][1].replace(",", ""))
                    else:
                        m = re.search(r"(\d{2,4})\s*(?:per night|/night)", card_text, re.I)
                        if m:
                            price_val = float(m.group(1))

                    # Drop container if it completely failed to extract basic info
                    if title == "Unknown Listing" and not price_val:
                        continue

                    # Rating Extraction
                    rating = None
                    m = re.search(r"(\d\.\d+)\s*out of 5", card_text)
                    if m:
                        rating = float(m.group(1))
                    else:
                        m2 = re.search(r"(\d\.\d+)\s*\(\d+\)", card_text)
                        if m2:
                            rating = float(m2.group(1))

                    # Image Extraction
                    image_url = None
                    try:
                        img_elem = card.find_element(By.CSS_SELECTOR, "img")
                        image_url = img_elem.get_attribute("src")
                    except Exception:
                        pass

                    # Commit to output stack
                    if not listing_url:
                        listing_url = f"https://www.airbnb.com/rooms/unknown_{random.randint(10000, 99999)}"

                    seen_urls.add(listing_url)
                    print(f"[airbnb] Successfully parsed item {len(raw_cards) + 1}: {title} -> {price_val}")

                    raw_cards.append({
                        "name": title,
                        "description": description,
                        "bedrooms": bedrooms,
                        "price_nightly": price_val,
                        "currency_symbol": detected_symbol,
                        "rating": rating,
                        "image_url": image_url,
                        "listing_url": listing_url,
                    })
                    if price_val:
                        prices.append(price_val)

                except Exception as e:
                    print(f"[airbnb] Temporary card skip item layout error: {e}")
                    continue

            # Nudge the page window down a viewport height to load the next block
            driver.execute_script("window.scrollBy(0, 650);")
            time.sleep(2)
            scroll_attempts += 1
            print(f"[airbnb] Scrolling down step {scroll_attempts}. Total scraped uniquely: {len(raw_cards)}")

        print(f"\n[airbnb] Pass 1 done: {len(raw_cards)} cards collected, {len(prices)} with prices.")

# ── PASS 2: fetch coordinates per listing ──────────────────────────────
        for item in raw_cards:
            lat, lng = None, None

            # Try 1: __NEXT_DATA__ on the listing page
            if item.get("listing_url"):
                result = _get_listing_coords(
                    driver, item["listing_url"], dest_lat, dest_lng
                )
                if result:
                    lat, lng = result

            # Try 2: Google Geocoding from listing name + city
            if lat is None:
                result = _geocode_name(item["name"], city_name, country)
                if result:
                    lat, lng = result

            # Try 3: jitter around destination centre (last resort)
            if lat is None:
                lat = dest_lat + random.uniform(-0.02, 0.02)
                lng = dest_lng + random.uniform(-0.02, 0.02)
                print(f"[coords] Jitter fallback for '{item['name']}'")

            item["latitude"] = lat
            item["longitude"] = lng
            listings_data.append(item)

        if prices:
            avg_price = round(sum(prices) / len(prices), 2)

    except Exception as e:
        print(f"[airbnb] Error: {e}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    # ── 3. Persist to DB ───────────────────────────────────────────────────────
    if listings_data:
        db = get_session()
        try:
            save_airbnb_listings(db, dest_id, listings_data, currency_symbol=detected_symbol)
            print(f"[airbnb] Saved {len(listings_data)} listings to DB for '{dest_id}'.")
        finally:
            db.close()

    return avg_price, listings_data


if __name__ == "__main__":
    print("--- Testing Standalone Airbnb Scraper ---")
    avg, details = scrape_airbnb_listings("Cancun", "Mexico", limit=10)
    print(f"\nAverage: {details[0]['currency_symbol'] if details else '?'}{avg or 'N/A'}/night")
    for item in details:
        sym = item.get("currency_symbol", "?")
        price = item.get("price_nightly")
        print(f"  - {item['name']}: {sym}{price}/night" if price else f"  - {item['name']}: no price")
