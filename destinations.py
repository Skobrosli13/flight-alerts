"""
Destination airport list for the Flight Deal Alerter.

Airports are grouped into tiers. The flat SEARCH_PRIORITY list determines
rotation order — tier-1 destinations appear first so they are always covered
even if the monthly API budget ceiling halts a cycle early.
"""

# Full human-readable names for use in email notifications
AIRPORT_NAMES = {
    # Domestic Tier 1
    "LAX": "Los Angeles",
    "SFO": "San Francisco",
    "MIA": "Miami",
    "MCO": "Orlando",
    "JFK": "New York (JFK)",
    "BOS": "Boston",
    "ORD": "Chicago (O'Hare)",
    "LAS": "Las Vegas",
    "SEA": "Seattle",
    "DEN": "Denver",
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
        "LAX", "SFO", "MIA", "MCO", "JFK", "BOS", "ORD", "LAS", "SEA", "DEN",
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


def get_destination_name(iata: str) -> str:
    return AIRPORT_NAMES.get(iata, iata)
