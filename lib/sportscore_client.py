"""
SportScore public API client.

SportScore (https://sportscore.com) provides a free, no-API-key REST
API for live sports data. Free tier: ~10,000 requests / 24h / IP,
CORS-open, JSON. We use it to supplement ESPN with data ESPN doesn't
provide or returns empty:

  - Standings (group tables) - ESPN doesn't have this at all
  - Knockout bracket - ESPN doesn't have this
  - Top scorers / assists - ESPN's summary endpoint returns empty
  - Lineups - ESPN's roster data is empty, SportScore returns full
    starting XIs with formation

Endpoints used (all GET, no auth):
  /api/widget/standings/?sport=football&slug=fifa-world-cup
  /api/widget/bracket/?sport=football&slug=fifa-world-cup
  /api/widget/topscorers/?sport=football&slug=fifa-world-cup&stat=goals
  /api/widget/match/?sport=football&slug={match-slug}
    -> returns lineups, incidents, stats, live_minute

Match slugs follow the pattern: {home}-vs-{away} (lowercase, hyphenated).
e.g. 'norway-vs-england', 'spain-vs-belgium'.

Rate limiting: we keep a 2-minute in-memory cache per endpoint+slug
so the webhook and cron job running close together don't double-hit.
"""
import json
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://sportscore.com"
WORLD_CUP_SLUG = "fifa-world-cup"

# 2-minute in-memory cache
_cache = {}
_cache_time = {}
_CACHE_TTL = 120  # seconds


def _request(path, params):
    """Make a GET request to SportScore. Returns the parsed JSON, or
    None on any failure."""
    query = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items() if v)
    url = f"{BASE_URL}{path}?{query}"

    cache_key = url
    now = datetime.now(timezone.utc)
    if cache_key in _cache and cache_key in _cache_time:
        if (now - _cache_time[cache_key]).total_seconds() < _CACHE_TTL:
            return _cache[cache_key]

    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (World Cup Bot)',
                'Accept': 'application/json',
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        _cache[cache_key] = data
        _cache_time[cache_key] = now
        return data
    except Exception as e:
        print(f"[sportscore] request failed for {url}: {e}")
        return None


def get_standings(competition_slug=WORLD_CUP_SLUG):
    """Get group-stage standings. Returns a list of group dicts, each
    with 'group' (name) and 'rows' (list of team standings).

    Each row has: pos, team, team_logo, played, won, drawn, lost,
    goals_for, goals_against, goal_diff, points.
    """
    data = _request("/api/widget/standings/", {
        "sport": "football",
        "slug": competition_slug,
    })
    if not data:
        return []
    return data.get("tables", []) or []


def get_bracket(competition_slug=WORLD_CUP_SLUG):
    """Get the knockout-stage bracket. Returns a list of round dicts,
    each with 'name' (e.g. 'Round of 16') and 'matchups' (list of
    matchup dicts with home/away/scores/winner)."""
    data = _request("/api/widget/bracket/", {
        "sport": "football",
        "slug": competition_slug,
    })
    if not data:
        return []
    return data.get("rounds", []) or []


def get_top_scorers(stat="goals", limit=10, competition_slug=WORLD_CUP_SLUG):
    """Get top scorers or assist leaders. stat is 'goals' or 'assists'.
    Returns a list of scorer dicts with: rank, player, team, goals,
    assists, matches, minutes, player_slug, team_slug."""
    data = _request("/api/widget/topscorers/", {
        "sport": "football",
        "slug": competition_slug,
        "stat": stat,
        "limit": limit,
    })
    if not data:
        return []
    return data.get("scorers", []) or []


def get_match_detail(match_slug):
    """Get detailed match data including lineups, incidents, stats.
    match_slug is like 'norway-vs-england'.
    Returns the match dict, or None if not found."""
    data = _request("/api/widget/match/", {
        "sport": "football",
        "slug": match_slug,
    })
    if not data:
        return None
    return data.get("match") or None


def get_lineups(match_slug):
    """Get the lineups for a match. Returns (home_lineup, away_lineup)
    where each is a dict with 'formation' and 'players' list, or
    (None, None) if not available."""
    match = get_match_detail(match_slug)
    if not match:
        return None, None
    lineups = match.get("lineups")
    if not lineups:
        return None, None
    # lineups is typically a list of 2 dicts: [home, away]
    if isinstance(lineups, list) and len(lineups) >= 2:
        return lineups[0], lineups[1]
    if isinstance(lineups, dict):
        return lineups.get("home"), lineups.get("away")
    return None, None


def find_match_slug(home_team, away_team):
    """Build the SportScore match slug from team names.
    Pattern: {home-lowercase-hyphenated}-vs-{away-lowercase-hyphenated}
    e.g. ('Norway', 'England') -> 'norway-vs-england'"""
    def slugify(name):
        # Simple slugify: lowercase, replace spaces with hyphens
        return name.lower().replace(" ", "-").replace(".", "").replace("'", "")
    return f"{slugify(home_team)}-vs-{slugify(away_team)}"
