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


def _listing_has_details(listing: dict) -> bool:
    name = (listing.get("name") or "").strip().lower()
    has_name = bool(name and name not in {"unknown", "unknown listing"})
    return has_name and bool(listing.get("listing_url")) and listing.get("price_nightly") is not None


def _cached_listings_are_usable(listings: list[dict]) -> bool:
    if not listings:
        return False
    detailed_count = sum(1 for listing in listings if _listing_has_details(listing))
    return detailed_count >= min(4, len(listings))


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
        if _cached_listings_are_usable(cached):
            print(f"[airbnb] Returning {len(cached)} cached listings for '{dest_id}'.")
            prices = [r["price_nightly"] for r in cached if r["price_nightly"]]
            avg = round(sum(prices) / len(prices), 2) if prices else None
            return avg, cached
        if cached:
            print(f"[airbnb] Ignoring incomplete cached listings for '{dest_id}'.")
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

        # Scroll aggressively to trigger lazy-loading. Streamlit/headless runs can
        # leave the first few cards partly empty, so load extras and filter below.
        desired_card_count = max(limit * 3, limit + 6)
        prev_count = 0
        for _ in range(6):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="card-container"]')
            print(f"[airbnb] Cards visible so far: {len(cards)}")
            if len(cards) >= desired_card_count:
                break
            if len(cards) == prev_count:
                # No new cards — scroll back up then down to re-trigger
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
            prev_count = len(cards)

        cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="card-container"]')
        print(f"[airbnb] Final card count: {len(cards)} (will collect up to {limit})")

            # ── PASS 1: read every card WITHOUT navigating away ────────────────────
        # Navigating away mid-loop causes Airbnb to rebuild the DOM on return,
        # which drops all remaining cards. Collect everything first.
        raw_cards: list[dict] = []

        for idx, card in enumerate(cards[:desired_card_count]):
            if len(raw_cards) >= limit:
                break
            try:
                # 🌟 CRITICAL FIX FOR HEADLESS CLOUD VIRTUALIZATION:
                # Scroll this specific card into the center of the viewport 
                # so Airbnb is forced to render its text, price, and inner elements.
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                time.sleep(1)  # Give it a brief moment to paint the text strings

                dom_data = driver.execute_script(
                    """
                    const card = arguments[0];
                    const textBits = [
                        card.innerText || "",
                        card.textContent || "",
                        card.getAttribute("aria-label") || "",
                    ];
                    const attrBits = Array.from(card.querySelectorAll("[aria-label], [title], img[alt]"))
                        .flatMap((el) => [
                            el.getAttribute("aria-label") || "",
                            el.getAttribute("title") || "",
                            el.getAttribute("alt") || "",
                        ]);
                    const links = Array.from(card.querySelectorAll('a[href*="/rooms/"]'))
                        .map((a) => a.href || a.getAttribute("href") || "")
                        .filter(Boolean);
                    const images = Array.from(card.querySelectorAll("img"))
                        .map((img) => ({
                            src: img.currentSrc || img.src || img.getAttribute("src") || "",
                            alt: img.getAttribute("alt") || "",
                        }))
                        .filter((img) => img.src || img.alt);
                    return { text: textBits.concat(attrBits).filter(Boolean).join("\\n"), links, images };
                    """,
                    card,
                )

                card_text = "\n".join(
                    part for part in [card.text, (dom_data or {}).get("text", "")]
                    if part
                )
                lines = [l.strip() for l in card_text.splitlines() if l.strip()]

                print(f"\n[airbnb] --- Card {idx + 1} ---")
                print(f"[airbnb] Preview: {card_text[:150]!r}")

                # Title
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
                if title == "Unknown Listing":
                    for image in (dom_data or {}).get("images", []):
                        alt = (image.get("alt") or "").strip()
                        if len(alt) > 8 and "image" not in alt.lower():
                            title = alt
                            break

                # Description
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

                # Bedrooms
                bed_parts = []
                for line in lines:
                    if re.search(r"\d+\s*(bedroom|bed|bathroom|studio)", line, re.I):
                        bed_parts.append(line)
                    if len(bed_parts) == 2:
                        break
                bedrooms = " · ".join(bed_parts) if bed_parts else None

                # Price — try multiple patterns
                price_val = None
                all_prices = re.findall(r"([£$€])([\d,]+)", card_text)
                print(f"[airbnb] All price matches: {all_prices}")
                if all_prices:
                    detected_symbol = all_prices[0][0]
                    price_val = float(all_prices[0][1].replace(",", ""))
                else:
                    # fallback: plain number followed by "per night" or "/night"
                    m = re.search(r"(\d{2,4})\s*(?:per night|/night)", card_text, re.I)
                    if m:
                        price_val = float(m.group(1))

                print(f"[airbnb] Title: {title!r} | Price: {price_val} | Bedrooms: {bedrooms!r}")

                if title == "Unknown Listing" and price_val is None:
                    print(f"[airbnb] Card {idx + 1} skipped: placeholder/no usable listing data")
                    continue

                # Rating
                rating = None
                m = re.search(r"(\d\.\d+)\s*out of 5", card_text)
                if m:
                    rating = float(m.group(1))
                else:
                    m2 = re.search(r"(\d\.\d+)\s*\(\d+\)", card_text)
                    if m2:
                        rating = float(m2.group(1))

                # Image
                image_url = None
                try:
                    img_elem = card.find_element(By.CSS_SELECTOR, "img")
                    image_url = img_elem.get_attribute("currentSrc") or img_elem.get_attribute("src")
                except Exception:
                    pass
                if not image_url:
                    for image in (dom_data or {}).get("images", []):
                        if image.get("src"):
                            image_url = image["src"]
                            break

                # Listing URL
                listing_url = None
                try:
                    link_elem = card.find_element(By.CSS_SELECTOR, 'a[href*="/rooms/"]')
                    href = link_elem.get_attribute("href")
                    listing_url = href if href.startswith("http") else f"https://www.airbnb.com{href}"
                except Exception:
                    pass
                if not listing_url:
                    for href in (dom_data or {}).get("links", []):
                        listing_url = href if href.startswith("http") else f"https://www.airbnb.com{href}"
                        break

                print(f"[airbnb] Has URL: {bool(listing_url)} | Has image: {bool(image_url)}")

                # Keep card even if no price — we still want it on the map
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
                print(f"[airbnb] Card {idx + 1} failed: {e}")
                continue

        print(f"\n[airbnb] Pass 1 done: {len(raw_cards)} cards collected, "
              f"{len(prices)} with prices.")

        # ── PASS 2: coordinates via geocoding only (no page navigation) ──────────
        for item in raw_cards:
            result = _geocode_name(item["name"], city_name, country)
            if result:
                lat, lng = result
            else:
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
