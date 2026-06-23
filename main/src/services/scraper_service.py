# Scrapes travel costs from the web. Google Flights has no proper API so this is a bit hacky.
#
# Data sources:
#   - Numbeo (numbeo.com) — meal prices, scraped from their cost-of-living pages
#   - Google Flights — we try to grab a price from the page HTML (often blocked)
#   - FALLBACK_COSTS below — our own researched estimates when scraping fails

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.config import COST_CACHE_TTL, ORIGIN_AIRPORT
from src.database.models import cache_costs, get_cached_costs, get_session


@dataclass
class CostEstimate:
    destination_id: str
    flight_estimate_usd: float
    hotel_nightly_usd: float
    airbnb_nightly_usd: float
    meal_index: float
    total_7_night_usd: float
    source: str


# Rough USD mid-range prices we looked up during research (Skyscanner, Booking, Numbeo).
# Not live prices — update if your demo needs fresher numbers.
FALLBACK_COSTS: dict[str, dict[str, float]] = {
    "bali": {"flight": 850, "hotel": 65, "airbnb": 45, "meal": 35},
    "phuket": {"flight": 780, "hotel": 50, "airbnb": 35, "meal": 25},
    "cancun": {"flight": 520, "hotel": 95, "airbnb": 70, "meal": 38},
    "miami": {"flight": 480, "hotel": 140, "airbnb": 100, "meal": 45},
    "rio": {"flight": 720, "hotel": 75, "airbnb": 55, "meal": 30},
    "honolulu": {"flight": 680, "hotel": 160, "airbnb": 120, "meal": 50},
    "punta-cana": {"flight": 490, "hotel": 110, "airbnb": 80, "meal": 35},
    "nassau": {"flight": 510, "hotel": 130, "airbnb": 95, "meal": 42},
    "gold-coast": {"flight": 1100, "hotel": 90, "airbnb": 65, "meal": 40},
    "san-juan": {"flight": 480, "hotel": 85, "airbnb": 60, "meal": 38},
}


class CostScraperService:
    NUMBEO_BASE = "https://www.numbeo.com/cost-of-living/in"

    def __init__(self, origin_airport: str | None = None) -> None:
        self.origin = origin_airport or ORIGIN_AIRPORT
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })

    def get_costs(
        self,
        destination_id: str,
        city_slug: str,
        airport_code: str,
    ) -> CostEstimate:
        db = get_session()
        try:
            cached = get_cached_costs(db, destination_id)
            if cached and self._row_is_fresh(cached):
                return self._from_row(cached)

            scraped = self._scrape_numbeo_meal_index(city_slug)
            flight = self._scrape_flight_hint(airport_code)
            fallback = FALLBACK_COSTS.get(
                destination_id, {"flight": 700, "hotel": 70, "airbnb": 50, "meal": 35}
            )

            flight_usd = flight or fallback["flight"]
            hotel = fallback["hotel"]
            airbnb = fallback["airbnb"] * (0.95 if scraped.get("cheap") else 1.0)
            meal = scraped.get("meal_index") or fallback["meal"]
            source = scraped.get("source", "fallback+baseline")

            cache_costs(db, destination_id, flight_usd, hotel, airbnb, meal, source)

            # flight + 7 nights hotel + 3 meals a day for 7 days
            total = flight_usd + (hotel * 7) + (meal * 7 * 3)
            return CostEstimate(
                destination_id=destination_id,
                flight_estimate_usd=flight_usd,
                hotel_nightly_usd=hotel,
                airbnb_nightly_usd=airbnb,
                meal_index=meal,
                total_7_night_usd=round(total, 2),
                source=source,
            )
        finally:
            db.close()

    def _scrape_numbeo_meal_index(self, city_slug: str) -> dict[str, Any]:
        url = f"{self.NUMBEO_BASE}/{city_slug}"
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                return {"source": f"numbeo-unavailable ({resp.status_code})"}

            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="data_wide_table")
            meal_index = None

            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        if "meal" in label and "inexpensive" in label:
                            val = re.search(r"[\d,.]+", cells[1].get_text())
                            if val:
                                meal_index = float(val.group().replace(",", ""))
                            break

            cheap = meal_index is not None and meal_index < 15
            return {"meal_index": meal_index, "cheap": cheap, "source": f"numbeo:{city_slug}"}
        except requests.RequestException:
            return {"source": "numbeo-scrape-failed"}

    def _scrape_flight_hint(self, dest_airport: str) -> float | None:
        # Google doesn't give us an API for this — scrape and hope for the best
        url = (
            f"https://www.google.com/travel/flights"
            f"?q=Flights%20from%20{self.origin}%20to%20{dest_airport}"
        )
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "lxml")
            text = soup.get_text(" ", strip=True)
            match = re.search(r"\$\s*([\d,]+)", text)
            if match:
                return float(match.group(1).replace(",", ""))
            meta = soup.find("meta", attrs={"property": "og:description"})
            if meta and meta.get("content"):
                m2 = re.search(r"\$\s*([\d,]+)", meta["content"])
                if m2:
                    return float(m2.group(1).replace(",", ""))
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def _row_is_fresh(row: Any) -> bool:
        from datetime import datetime, timezone

        if not row.fetched_at:
            return False
        ts = row.fetched_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < COST_CACHE_TTL

    @staticmethod
    def _from_row(row: Any) -> CostEstimate:
        total = row.flight_estimate_usd + (row.hotel_nightly_usd * 7) + (row.meal_index * 7 * 3)
        return CostEstimate(
            destination_id=row.destination_id,
            flight_estimate_usd=row.flight_estimate_usd,
            hotel_nightly_usd=row.hotel_nightly_usd,
            airbnb_nightly_usd=row.airbnb_nightly_usd,
            meal_index=row.meal_index,
            total_7_night_usd=round(total, 2),
            source=row.source or "cache",
        )


NUMBEO_SLUGS: dict[str, str] = {
    "bali": "Denpasar",
    "phuket": "Phuket",
    "cancun": "Cancun",
    "miami": "Miami",
    "rio": "Rio-De-Janeiro",
    "honolulu": "Honolulu",
    "punta-cana": "Punta-Cana",
    "nassau": "Nassau",
    "gold-coast": "Gold-Coast",
    "san-juan": "San-Juan",
}
