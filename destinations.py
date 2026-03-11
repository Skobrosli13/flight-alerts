"""
Destination airport list for the Flight Deal Alerter.

Airports are grouped into tiers. The flat SEARCH_PRIORITY list determines
rotation order — tier-1 destinations appear first so they are always covered
even if the monthly API budget ceiling halts a cycle early.
"""

# Full human-readable names for use in email notifications
AIRPORT_NAMES = {
    # Origin
    "IAD": "Washington D.C. (Dulles)",
    # Domestic Tier 1
    "LAX": "Los Angeles",
    "MIA": "Miami",
    "BOS": "Boston",
    "ORD": "Chicago (O'Hare)",
    "LAS": "Las Vegas",
    # Caribbean & Mexico
    "CUN": "Cancun",
    "MBJ": "Montego Bay",
    "PUJ": "Punta Cana",
    # Europe Tier 1
    "LHR": "London (Heathrow)",
    "CDG": "Paris (CDG)",
    "FCO": "Rome (Fiumicino)",
    "BCN": "Barcelona",
    # Europe Tier 2
    "LIS": "Lisbon",
    "MAD": "Madrid",
    # Middle East
    "BEY": "Beirut",
    "TLV": "Tel Aviv",
    "IST": "Istanbul",
    "CAI": "Cairo",
    # Asia-Pacific
    "NRT": "Tokyo (Narita)",
    "BKK": "Bangkok",
    "SYD": "Sydney",
}

DESTINATIONS = {
    "domestic_tier1": [
        "LAX", "MIA", "BOS", "ORD", "LAS",
    ],
    "caribbean_mexico": [
        "CUN", "MBJ", "PUJ",
    ],
    "europe_tier1": [
        "LHR", "CDG", "FCO", "BCN",
    ],
    "europe_tier2": [
        "LIS", "MAD",
    ],
    "middle_east": [
        "BEY", "TLV", "IST", "CAI",
    ],
    "asia_pacific": [
        "NRT", "BKK", "SYD",
    ],
}

# Flat ordered list for rotation. Higher-priority regions come first.
SEARCH_PRIORITY: list[str] = (
    DESTINATIONS["domestic_tier1"]
    + DESTINATIONS["caribbean_mexico"]
    + DESTINATIONS["europe_tier1"]
    + DESTINATIONS["europe_tier2"]
    + DESTINATIONS["middle_east"]
    + DESTINATIONS["asia_pacific"]
)

assert len(SEARCH_PRIORITY) == len(set(SEARCH_PRIORITY)), "Duplicate destinations found"

DOMESTIC_DESTINATIONS: set[str] = set(DESTINATIONS["domestic_tier1"])
CARIBBEAN_DESTINATIONS: set[str] = set(DESTINATIONS["caribbean_mexico"])
# Destinations subject to the weekend-only departure/return rule — search all 4 Thu/Fri × Sun/Mon combos
WEEKEND_DATE_DESTINATIONS: set[str] = {"MIA", "BOS"} | set(DESTINATIONS["caribbean_mexico"])
EUROPE_DESTINATIONS: set[str] = set(
    DESTINATIONS["europe_tier1"]
    + DESTINATIONS["europe_tier2"]
)
MIDDLE_EAST_ASIA_DESTINATIONS: set[str] = set(
    DESTINATIONS["middle_east"]
    + DESTINATIONS["asia_pacific"]
)


def get_destination_name(iata: str) -> str:
    return AIRPORT_NAMES.get(iata, iata)
