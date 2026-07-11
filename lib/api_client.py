"""
ESPN public scoreboard API client.

ESPN's site.api.espn.com endpoints are free, undocumented-but-stable,
and need no API key or account. We keep a short in-memory cache
(2 minutes) purely to avoid duplicate calls within a single process run -
each cron invocation is a fresh process anyway, so this does not replace
being reasonably gentle with request frequency (main_monitor.py is meant
to run once every 1-2 minutes via a scheduled task, not in a loop).

Important: the default scoreboard endpoint only returns events for the
current "week" (typically just today + a couple of nearby days). To find
upcoming fixtures we always request a 30-day window starting today via
the `dates` query parameter - without it, the "next match" button on the
bot menu and the pre-match cron notifications silently see no upcoming
games and report "no scheduled matches".
"""
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

# How many days ahead to look when fetching the scoreboard. 30 days covers
# the rest of a World Cup from any point in the tournament and keeps the
# response payload small enough for a 256MB free-plan server.
FIXTURE_WINDOW_DAYS = 30

# Translate ESPN's English stage names to Persian for display. Falls back
# to the English name (or a generic label) for anything not listed here.
_STAGE_FA = {
    'Group': 'مرحله گروهی جام جهانی ۲۰۲۶',
    'Round of 32': 'یک‌سی‌ودوم نهایی جام جهانی ۲۰۲۶',
    'Rd of 16': 'یک‌شانزدهم نهایی جام جهانی ۲۰۲۶',
    'Round of 16': 'یک‌شانزدهم نهایی جام جهانی ۲۰۲۶',
    'Quarterfinals': 'یک‌چهارم نهایی جام جهانی ۲۰۲۶',
    'Semifinals': 'نیمه‌نهایی جام جهانی ۲۰۲۶',
    '3rd-Place Match': 'دیدار رده‌بندی جام جهانی ۲۰۲۶',
    'Final': 'فینال جام جهانی ۲۰۲۶',
    'FIFA World Cup, Group': 'مرحله گروهی جام جهانی ۲۰۲۶',
    'FIFA World Cup, Round of 32': 'یک‌سی‌ودوم نهایی جام جهانی ۲۰۲۶',
    'FIFA World Cup, Round of 16': 'یک‌شانزدهم نهایی جام جهانی ۲۰۲۶',
    'FIFA World Cup, Quarterfinals': 'یک‌چهارم نهایی جام جهانی ۲۰۲۶',
    'FIFA World Cup, Semifinals': 'نیمه‌نهایی جام جهانی ۲۰۲۶',
    'FIFA World Cup, 3rd-Place Match': 'دیدار رده‌بندی جام جهانی ۲۰۲۶',
    'FIFA World Cup, Final': 'فینال جام جهانی ۲۰۲۶',
}


def _load_league():
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('api', {}).get('league', 'fifa.world')
    except Exception:
        return 'fifa.world'


class FootballAPIClient:
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

    def __init__(self, league=None):
        self.league = league or _load_league()
        self.cache = {}
        self.cache_time = None

    def _request(self, url):
        try:
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            print(f"[api_client] ESPN request failed: {e}")
            return None

    def _date_range(self):
        """Build the `dates=YYYYMMDD-YYYYMMDD` query window starting today."""
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=FIXTURE_WINDOW_DAYS)
        return f"{today.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"

    def _get_scoreboard(self):
        cache_key = f"scoreboard_{self.league}"
        now = datetime.now(timezone.utc)
        if (
            cache_key in self.cache
            and self.cache_time
            and (now - self.cache_time).total_seconds() < 120
        ):
            return self.cache[cache_key]
        # `dates` is what makes ESPN return upcoming fixtures too - without
        # it the scoreboard only shows events from the current week, which
        # during the knockout stage can be just one already-finished match.
        url = f"{self.BASE_URL}/{self.league}/scoreboard?dates={self._date_range()}"
        data = self._request(url)
        if data:
            self.cache[cache_key] = data
            self.cache_time = now
        return data

    def get_live_fixtures(self):
        data = self._get_scoreboard()
        if not data:
            return []
        return [
            e for e in data.get('events', [])
            if e.get('status', {}).get('type', {}).get('state') == 'in'
        ]

    def get_all_fixtures(self):
        data = self._get_scoreboard()
        return data.get('events', []) if data else []

    def parse_event(self, event):
        comps = event.get('competitions', [{}])[0]
        status = event.get('status', {}).get('type', {})

        teams_map = {}
        for comp in comps.get('competitors', []):
            tid = comp.get('team', {}).get('id', '')
            tname = comp.get('team', {}).get('displayName', '')
            teams_map[tid] = tname

        competitors = comps.get('competitors', [])
        home = next((c for c in competitors if c.get('homeAway') == 'home'), {})
        away = next((c for c in competitors if c.get('homeAway') == 'away'), {})

        details = comps.get('details', [])
        goals, cards, penalties, substitutions = [], [], [], []
        for d in details:
            event_type = d.get('type', {}).get('text', '')
            team_id = d.get('team', {}).get('id', '')
            team_name = teams_map.get(team_id, '?')
            clock = d.get('clock', {}).get('displayValue', '?')
            athletes = d.get('athletesInvolved', [])
            player_name = athletes[0].get('displayName', '?') if athletes else '?'

            if 'Penalty' in event_type:
                # Shootout penalties (post-90/120min). scoringPlay tells us
                # whether it went in; ESPN doesn't reliably label save vs miss,
                # so we fall back to a generic "missed" when it wasn't scored.
                scored = bool(d.get('scoringPlay'))
                penalties.append({
                    'team': team_name, 'player': player_name,
                    'minute': clock, 'scored': scored,
                    'detail': event_type,
                })
            elif event_type == 'Goal':
                goals.append({
                    'team': team_name, 'player': player_name,
                    'minute': clock, 'detail': 'گل عادی',
                })
            elif 'Card' in event_type:
                cd = 'کارت زرد' if 'Yellow' in event_type else 'کارت قرمز'
                cards.append({
                    'team': team_name, 'player': player_name,
                    'minute': clock, 'detail': cd,
                })
            elif event_type == 'Substitution':
                # Substitutions have 2 athletes: [out, in]
                # ESPN text: "Substitution, Spain. Ferran Torres replaces Álex Baena."
                # athletesInvolved: [ Torres (coming on), Baena (going off) ]
                out_player = athletes[1].get('displayName', '?') if len(athletes) > 1 else '?'
                in_player = athletes[0].get('displayName', '?') if athletes else '?'
                substitutions.append({
                    'team': team_name,
                    'out': out_player,
                    'in': in_player,
                    'minute': clock,
                })

        # Stage label - ESPN stores this in season.type.name (e.g.
        # "Quarterfinals") and also in competitions[0].altGameNote
        # ("FIFA World Cup, Quarterfinals"). We translate the most common
        # English stage names to Persian so users don't see raw English.
        # Note: season.type can sometimes be just an int (the type id), so
        # we use a chain of .get() calls with empty-dict fallbacks.
        season_type = event.get('season', {}).get('type') or {}
        if not isinstance(season_type, dict):
            season_type = {}
        stage_en = (
            season_type.get('name', '')
            or comps.get('altGameNote', '')
            or ''
        )
        stage_fa = _STAGE_FA.get(stage_en, stage_en if stage_en else 'جام جهانی ۲۰۲۶')

        # City + country of the venue, for nicer pre-match messages.
        venue_addr = comps.get('venue', {}).get('address', {}) or {}
        venue_city = venue_addr.get('city', '') or ''

        return {
            'id': event.get('id'),
            'name': event.get('name', ''),
            'date': event.get('date', ''),
            'home_team': home.get('team', {}).get('displayName', ''),
            'away_team': away.get('team', {}).get('displayName', ''),
            'home_score': int(home.get('score', 0) or 0),
            'away_score': int(away.get('score', 0) or 0),
            'status': status.get('name', ''),
            'status_state': status.get('state', ''),
            'clock': event.get('status', {}).get('displayClock', "0'"),
            'venue': comps.get('venue', {}).get('fullName', ''),
            'venue_city': venue_city,
            'stage': stage_fa,
            'goals': goals,
            'cards': cards,
            'penalties': penalties,
            'substitutions': substitutions,
            'minute': self._parse_clock(event.get('status', {}).get('displayClock', "0'")),
            'details': details,
            'teams_map': teams_map,
        }

    def _parse_clock(self, clock_str):
        try:
            clean = clock_str.replace("'", "").replace("’", "")
            if '+' in clean:
                parts = clean.split('+')
                return int(parts[0]) + int(parts[1])
            return int(clean)
        except Exception:
            return 0
