# The list of destinations we compare. Edit here if you want to add or swap a location.
# When you add one, also update NUMBEO_SLUGS and FALLBACK_COSTS in scraper_service.py.

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    id: str
    name: str
    country: str
    latitude: float
    longitude: float
    airport_code: str
    description: str
    adventure_tags: tuple[str, ...]
    nightlife_score: int  # our rough 1-10 rating, not from an API


# The 10 places we compare — picked because people actually know them.
DESTINATIONS: list[Destination] = [
    Destination(
        id="bali",
        name="Bali",
        country="Indonesia",
        latitude=-8.4095,
        longitude=115.1889,
        airport_code="DPS",
        description="Beaches and temples, surf around Uluwatu, busy bars in Seminyak and Kuta.",
        adventure_tags=("surfing", "temples", "diving", "hiking"),
        nightlife_score=9,
    ),
    Destination(
        id="phuket",
        name="Phuket",
        country="Thailand",
        latitude=7.8804,
        longitude=98.3923,
        airport_code="HKT",
        description="Thailand's biggest island — Patong nightlife, island hopping, and limestone bays.",
        adventure_tags=("island-hopping", "diving", "street-food", "snorkeling"),
        nightlife_score=9,
    ),
    Destination(
        id="cancun",
        name="Cancún",
        country="Mexico",
        latitude=21.1619,
        longitude=-86.8515,
        airport_code="CUN",
        description="Big hotel strip and clubs, reefs nearby, easy day trips to Tulum and Playa.",
        adventure_tags=("snorkeling", "ruins", "diving", "nightlife"),
        nightlife_score=10,
    ),
    Destination(
        id="miami",
        name="Miami",
        country="USA",
        latitude=25.7617,
        longitude=-80.1918,
        airport_code="MIA",
        description="South Beach, Art Deco, Wynwood, and one of the best club scenes in the US.",
        adventure_tags=("beach", "culture", "food", "water-sports"),
        nightlife_score=10,
    ),
    Destination(
        id="rio",
        name="Rio de Janeiro",
        country="Brazil",
        latitude=-22.9068,
        longitude=-43.1729,
        airport_code="GIG",
        description="Christ statue, Copacabana and Ipanema, samba, messy beach parties.",
        adventure_tags=("hiking", "beach", "culture", "surfing"),
        nightlife_score=10,
    ),
    Destination(
        id="honolulu",
        name="Honolulu",
        country="USA",
        latitude=21.3069,
        longitude=-157.8583,
        airport_code="HNL",
        description="Waikiki, Pearl Harbor, Diamond Head hikes, and a solid bar scene after sunset.",
        adventure_tags=("surfing", "hiking", "snorkeling", "history"),
        nightlife_score=8,
    ),
    Destination(
        id="punta-cana",
        name="Punta Cana",
        country="Dominican Republic",
        latitude=18.5601,
        longitude=-68.3725,
        airport_code="PUJ",
        description="Resort zone, clear water, golf, bars in the hotel strip.",
        adventure_tags=("snorkeling", "golf", "beach", "catamaran"),
        nightlife_score=8,
    ),
    Destination(
        id="nassau",
        name="Nassau",
        country="Bahamas",
        latitude=25.0443,
        longitude=-77.3504,
        airport_code="NAS",
        description="Cable Beach, Paradise Island, swimming pigs day trips, and waterfront bars.",
        adventure_tags=("snorkeling", "boating", "beach", "culture"),
        nightlife_score=8,
    ),
    Destination(
        id="gold-coast",
        name="Gold Coast",
        country="Australia",
        latitude=-28.0167,
        longitude=153.4000,
        airport_code="OOL",
        description="Surfers Paradise — theme parks by day, big nights out on the strip.",
        adventure_tags=("surfing", "theme-parks", "hiking", "wildlife"),
        nightlife_score=8,
    ),
    Destination(
        id="san-juan",
        name="San Juan",
        country="Puerto Rico",
        latitude=18.4655,
        longitude=-66.1057,
        airport_code="SJU",
        description="Old town, rainforest hikes, bioluminescent bay trips, decent bar scene.",
        adventure_tags=("rainforest", "culture", "beach", "history"),
        nightlife_score=9,
    ),
]


def get_destination_by_id(dest_id: str) -> Destination | None:
    return next((d for d in DESTINATIONS if d.id == dest_id), None)
