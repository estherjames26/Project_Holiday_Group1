# Scrapes trip costs from the web (Numbeo + Cheapflights).
# Falls back to hardcoded estimates if a scrape fails.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from settings import COST_CACHE_TTL, GBP_TO_USD, ORIGIN_AIRPORT
from database import cache_costs, get_cached_costs, get_session


@dataclass
class CostEstimate:
    destination_id: str
    flight_estimate_usd: float
    hotel_nightly_usd: float
    airbnb_nightly_usd: float
    meal_index: float
    total_7_night_usd: float
    source: str
    scrape_sources: dict[str, str] = field(default_factory=dict)


# Rough prices used only when web scraping fails.
FALLBACK_COSTS: dict[str, dict[str, float]] = {    "bali": {"flight": 850, "hotel": 65, "airbnb": 45, "meal": 35},
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

# Known Numbeo slugs for seed destinations and common aliases.
NUMBEO_SLUGS: dict[str, str] = {
    "bali": "Denpasar",
    "phuket": "Phuket",
    "cancun": "Cancun",
    "miami": "Miami",
    "rio": "Rio-De-Janeiro",
    "rio-de-janeiro": "Rio-De-Janeiro",
    "honolulu": "Honolulu",
    "punta-cana": "Punta-Cana",
    "nassau": "Nassau",
    "gold-coast": "Gold-Coast",
    "surfers-paradise": "Gold-Coast",
    "san-juan": "San-Juan",
    "carolina": "San-Juan",
    "langkawi": "Langkawi",
    "cartagena": "Cartagena",
    "cartagena-de-indias": "Cartagena",
    "bang-lamung-district": "Pattaya",
    "badung-regency": "Denpasar",
    "kabupaten-badung": "Denpasar",
}

# When Numbeo has no page for a small town, try a nearby hub in the same country.
NUMBEO_COUNTRY_FALLBACKS: dict[str, str] = {
    "Malaysia": "Kuala-Lumpur",
    "Puerto Rico": "San-Juan",
    "Thailand": "Phuket",
    "Indonesia": "Denpasar",
    "Mexico": "Cancun",
    "Colombia": "Cartagena",
    "The Bahamas": "Nassau",
    "Bahamas": "Nassau",
}


class CostScraperService:
    NUMBEO_BASE = "https://www.numbeo.com/cost-of-living/in"
    CHEAPFLIGHTS_BASE = "https://www.cheapflights.co.uk/flights-to"

    def __init__(self, origin_airport: str | None = None) -> None:
        self.origin = origin_airport or ORIGIN_AIRPORT
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        })

    def get_costs(
        self,
        destination_id: str,
        city_name: str,
        country: str = "",
        airport_code: str = "",
    ) -> CostEstimate:
        db = get_session()
        try:
            cached = get_cached_costs(db, destination_id)
            if cached and self._row_is_fresh(cached):
                return self._from_row(cached)

            numbeo_slug = self._resolve_numbeo_slug(destination_id, city_name, country)
            numbeo = self._scrape_numbeo(numbeo_slug) if numbeo_slug else {}

            flight_slug = self._resolve_cheapflights_slug(city_name, country)
            flight_usd, flight_source = self._scrape_cheapflights(flight_slug)

            fallback = FALLBACK_COSTS.get(
                destination_id,
                {"flight": 700, "hotel": 70, "airbnb": 50, "meal": 35},
            )

            scrape_sources: dict[str, str] = {}

            if flight_usd is not None:
                scrape_sources["flight"] = flight_source
            else:
                flight_usd = self._scrape_flight_hint(airport_code) or fallback["flight"]
                scrape_sources["flight"] = (
                    "google-flights-scrape" if flight_usd != fallback["flight"] else "fallback"
                )

            meal = numbeo.get("meal_inexpensive") or fallback["meal"]
            scrape_sources["meal"] = numbeo.get("meal_source", "fallback")

            if numbeo.get("rent_monthly_usd"):
                airbnb = round(numbeo["rent_monthly_usd"] / 30, 2)
                hotel = round(airbnb * 1.35, 2)
                scrape_sources["airbnb"] = "numbeo-rent-scrape"
                scrape_sources["hotel"] = "numbeo-rent-estimate"
            else:
                airbnb = fallback["airbnb"] * (0.95 if numbeo.get("cheap") else 1.0)
                hotel = fallback["hotel"]
                scrape_sources["airbnb"] = "fallback"
                scrape_sources["hotel"] = "fallback"

            source_parts = sorted({v for v in scrape_sources.values() if v != "fallback"})
            source = "+".join(source_parts) if source_parts else "fallback"

            cache_costs(
                db,
                destination_id,
                flight_usd,
                hotel,
                airbnb,
                meal,
                source,
            )

            total = flight_usd + (hotel * 7) + (meal * 7 * 3)
            return CostEstimate(
                destination_id=destination_id,
                flight_estimate_usd=flight_usd,
                hotel_nightly_usd=hotel,
                airbnb_nightly_usd=airbnb,
                meal_index=meal,
                total_7_night_usd=round(total, 2),
                source=source,
                scrape_sources=scrape_sources,
            )
        finally:
            db.close()

    def _resolve_numbeo_slug(self, destination_id: str, city_name: str, country: str) -> str | None:
        candidates: list[str] = []

        if destination_id in NUMBEO_SLUGS:
            candidates.append(NUMBEO_SLUGS[destination_id])

        slug_from_name = re.sub(r"[^a-zA-Z0-9]+", "-", city_name).strip("-")
        candidates.extend([
            slug_from_name,
            slug_from_name.title(),
            city_name.replace(" ", "-"),
            city_name.split(",")[0].strip().replace(" ", "-"),
            city_name.split()[0],
        ])

        if country:
            candidates.append(f"{city_name.split()[0]}-{country.split()[0]}")
            if country in NUMBEO_COUNTRY_FALLBACKS:
                candidates.append(NUMBEO_COUNTRY_FALLBACKS[country])

        seen: set[str] = set()
        for slug in candidates:
            slug = slug.strip("-")
            if not slug or slug.lower() in seen:
                continue
            seen.add(slug.lower())
            if self._numbeo_page_exists(slug):
                return slug
        return None

    def _numbeo_page_exists(self, slug: str) -> bool:
        try:
            resp = self.session.get(
                f"{self.NUMBEO_BASE}/{quote(slug)}",
                params={"displayCurrency": "USD"},
                timeout=15,
            )
            if resp.status_code != 200:
                return False
            title = BeautifulSoup(resp.text, "lxml").find("title")
            return bool(title and "Cost of Living" in title.get_text())
        except requests.RequestException:
            return False

    def _scrape_numbeo(self, slug: str) -> dict[str, Any]:
        url = f"{self.NUMBEO_BASE}/{quote(slug)}"
        try:
            resp = self.session.get(url, params={"displayCurrency": "USD"}, timeout=20)
            if resp.status_code != 200:
                return {"source": f"numbeo-unavailable ({resp.status_code})"}

            soup = BeautifulSoup(resp.text, "lxml")
            table = soup.find("table", class_="data_wide_table")
            if not table:
                return {"source": "numbeo-no-table"}

            meal_inexpensive = None
            rent_monthly = None

            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(strip=True).lower()
                value = self._parse_usd(cells[1].get_text(strip=True))
                if value is None:
                    continue

                if "meal" in label and "inexpensive" in label:
                    meal_inexpensive = value
                elif "1 bedroom apartment" in label and "city centre" in label:
                    rent_monthly = value

            cheap = meal_inexpensive is not None and meal_inexpensive < 15
            return {
                "meal_inexpensive": meal_inexpensive,
                "rent_monthly_usd": rent_monthly,
                "cheap": cheap,
                "meal_source": f"numbeo-scrape:{slug}",
                "source": f"numbeo:{slug}",
            }
        except requests.RequestException:
            return {"source": "numbeo-scrape-failed"}

    @staticmethod
    def _parse_usd(text: str) -> float | None:
        cleaned = text.replace(",", "").strip()
        match = re.search(r"\$\s*([\d.]+)", cleaned)
        if match:
            return float(match.group(1))
        match = re.search(r"([\d.]+)", cleaned)
        if match and "$" in text:
            return float(match.group(1))
        return None

    @staticmethod
    def _resolve_cheapflights_slug(city_name: str, country: str) -> str:
        primary = city_name.split(",")[0].strip()
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", primary.lower()).strip("-")
        slug_map = {
            "rio-de-janeiro": "rio-de-janeiro",
            "carolina": "san-juan",
            "cartagena-de-indias": "cartagena",
            "bang-lamung-district": "phuket",
            "badung-regency": "bali",
            "kabupaten-badung": "bali",
            "surfers-paradise": "gold-coast",
            "ciudad-de-mexico": "cancun",
            "panama-city-beach": "miami",
        }
        return slug_map.get(slug, slug)

    def _scrape_cheapflights(self, city_slug: str) -> tuple[float | None, str]:
        """Scrape minimum return fare from Cheapflights UK listing pages."""
        url = f"{self.CHEAPFLIGHTS_BASE}-{city_slug}/"
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                return None, "cheapflights-unavailable"

            soup = BeautifulSoup(resp.text, "lxml")
            title = soup.find("title")
            if title:
                match = re.search(r"£([\d,]+)\+", title.get_text())
                if match:
                    gbp = float(match.group(1).replace(",", ""))
                    usd = round(gbp * GBP_TO_USD, 2)
                    return usd, f"cheapflights-scrape:{city_slug}"

            prices = re.findall(r"£([\d,]+)", resp.text)
            nums = [
                int(p.replace(",", ""))
                for p in prices
                if p.replace(",", "").isdigit() and 80 <= int(p.replace(",", "")) <= 2500
            ]
            if nums:
                usd = round(min(nums) * GBP_TO_USD, 2)
                return usd, f"cheapflights-scrape:{city_slug}"
        except requests.RequestException:
            pass
        return None, "cheapflights-scrape-failed"

    def _scrape_flight_hint(self, dest_airport: str) -> float | None:
        if not dest_airport or len(dest_airport) != 3:
            return None
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
            scrape_sources={"cached": row.source or "cache"},
        )
