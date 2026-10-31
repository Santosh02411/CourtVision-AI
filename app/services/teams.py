"""Static NBA franchise metadata + season helpers (no network)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

# abbr: (team_id, city, nickname, conference, division, primary, secondary)
_TEAMS: dict[str, tuple[int, str, str, str, str, str, str]] = {
    "ATL": (1610612737, "Atlanta", "Hawks", "East", "Southeast", "#E03A3E", "#C1D32F"),
    "BOS": (1610612738, "Boston", "Celtics", "East", "Atlantic", "#007A33", "#BA9653"),
    "BKN": (1610612751, "Brooklyn", "Nets", "East", "Atlantic", "#8A8D8F", "#000000"),
    "CHA": (1610612766, "Charlotte", "Hornets", "East", "Southeast", "#00788C", "#1D1160"),
    "CHI": (1610612741, "Chicago", "Bulls", "East", "Central", "#CE1141", "#000000"),
    "CLE": (1610612739, "Cleveland", "Cavaliers", "East", "Central", "#860038", "#FDBB30"),
    "DAL": (1610612742, "Dallas", "Mavericks", "West", "Southwest", "#0064B1", "#00285E"),
    "DEN": (1610612743, "Denver", "Nuggets", "West", "Northwest", "#FEC524", "#0E2240"),
    "DET": (1610612765, "Detroit", "Pistons", "East", "Central", "#C8102E", "#1D42BA"),
    "GSW": (1610612744, "Golden State", "Warriors", "West", "Pacific", "#FFC72C", "#1D428A"),
    "HOU": (1610612745, "Houston", "Rockets", "West", "Southwest", "#CE1141", "#C4CED4"),
    "IND": (1610612754, "Indiana", "Pacers", "East", "Central", "#FDBB30", "#002D62"),
    "LAC": (1610612746, "LA", "Clippers", "West", "Pacific", "#C8102E", "#1D428A"),
    "LAL": (1610612747, "Los Angeles", "Lakers", "West", "Pacific", "#FDB927", "#552583"),
    "MEM": (1610612763, "Memphis", "Grizzlies", "West", "Southwest", "#5D76A9", "#12173F"),
    "MIA": (1610612748, "Miami", "Heat", "East", "Southeast", "#98002E", "#F9A01B"),
    "MIL": (1610612749, "Milwaukee", "Bucks", "East", "Central", "#00471B", "#EEE1C6"),
    "MIN": (1610612750, "Minnesota", "Timberwolves", "West", "Northwest", "#236192", "#78BE20"),
    "NOP": (1610612740, "New Orleans", "Pelicans", "West", "Southwest", "#85714D", "#0C2340"),
    "NYK": (1610612752, "New York", "Knicks", "East", "Atlantic", "#F58426", "#006BB6"),
    "OKC": (1610612760, "Oklahoma City", "Thunder", "West", "Northwest", "#007AC1", "#EF3B24"),
    "ORL": (1610612753, "Orlando", "Magic", "East", "Southeast", "#0077C0", "#C4CED4"),
    "PHI": (1610612755, "Philadelphia", "76ers", "East", "Atlantic", "#006BB6", "#ED174C"),
    "PHX": (1610612756, "Phoenix", "Suns", "West", "Pacific", "#E56020", "#1D1160"),
    "POR": (1610612757, "Portland", "Trail Blazers", "West", "Northwest", "#E03A3E", "#000000"),
    "SAC": (1610612758, "Sacramento", "Kings", "West", "Pacific", "#5A2D81", "#63727A"),
    "SAS": (1610612759, "San Antonio", "Spurs", "West", "Southwest", "#8A8D8F", "#000000"),
    "TOR": (1610612761, "Toronto", "Raptors", "East", "Atlantic", "#CE1141", "#000000"),
    "UTA": (1610612762, "Utah", "Jazz", "West", "Northwest", "#F9A01B", "#002B5C"),
    "WAS": (1610612764, "Washington", "Wizards", "East", "Southeast", "#E31837", "#002B5C"),
}

ALIASES = {"NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA"}

TEAMS: dict[int, dict[str, Any]] = {}
BY_ABBR: dict[str, dict[str, Any]] = {}
for _abbr, (_id, _city, _nick, _conf, _div, _p, _s) in _TEAMS.items():
    _row = {
        "id": _id, "abbr": _abbr, "city": _city, "nickname": _nick, "name": f"{_city} {_nick}",
        "conference": _conf, "division": _div, "primary": _p, "secondary": _s,
        "logo": f"https://cdn.nba.com/logos/nba/{_id}/global/L/logo.svg",
    }
    TEAMS[_id] = _row
    BY_ABBR[_abbr] = _row


def normalize_abbr(value: Any) -> str:
    v = str(value or "").strip().upper()
    return ALIASES.get(v, v)


def team_by_abbr(value: Any) -> dict[str, Any] | None:
    return BY_ABBR.get(normalize_abbr(value))


def team_by_id(value: Any) -> dict[str, Any] | None:
    try:
        return TEAMS.get(int(value))
    except (TypeError, ValueError):
        return None


def resolve_team(value: Any) -> dict[str, Any] | None:
    """Accept an abbreviation, numeric id, or a case-insensitive name/nickname."""
    if value is None or value == "":
        return None
    team = team_by_abbr(value) or team_by_id(value)
    if team:
        return team
    needle = str(value).strip().lower()
    for row in TEAMS.values():
        if needle in (row["name"].lower(), row["nickname"].lower(), row["city"].lower()):
            return row
    return None


def headshot_url(player_id: Any) -> str:
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{int(player_id)}.png"


# -- seasons ------------------------------------------------------------------
_SEASON_RE = re.compile(r"^(\d{4})-(\d{2})$")
FIRST_SUPPORTED_START = 2015


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def current_season(today: date | None = None) -> str:
    """The NBA season in progress. A new season label begins in October (tip-off is mid/late Oct)."""
    today = today or date.today()
    return season_label(today.year if today.month >= 10 else today.year - 1)


def previous_season(season: str) -> str:
    return season_label(int(season[:4]) - 1)


def recent_seasons(season: str, count: int) -> list[str]:
    start = int(season[:4])
    return [season_label(start - i) for i in range(count)]


def valid_season(value: str | None, today: date | None = None) -> str | None:
    """Return a normalised season label, or None if malformed / out of the supported range."""
    if not value:
        return None
    m = _SEASON_RE.match(value.strip())
    if not m:
        return None
    start, tail = int(m.group(1)), m.group(2)
    if tail != f"{(start + 1) % 100:02d}":
        return None
    if start < FIRST_SUPPORTED_START or start > int(current_season(today)[:4]):
        return None
    return season_label(start)


def season_id(season: str) -> str:
    return "2" + season[:4]


def season_options(today: date | None = None, count: int = 8) -> list[str]:
    return recent_seasons(current_season(today), count)
