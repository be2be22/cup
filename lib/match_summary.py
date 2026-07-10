"""
ESPN match summary enrichment.

Pulls richer per-match data from ESPN's `summary` endpoint that the
scoreboard doesn't have - last-5-games form, head-to-head history,
team leaders (top scorer / assister / shot-taker), and betting odds.
Used to feed the AI analysis real, current tournament data instead
of relying on the AI's stale training-set knowledge of who's injured
or called up.

The endpoint URL pattern is:
  https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event_id}

Returns None on any failure so callers can fall back to the basic
scoreboard-only flow without crashing.
"""
import json
import urllib.request
from datetime import datetime, timezone

from lib.formatter import fa, TEAM_FA, to_jalali


# 2-minute in-memory cache so the webhook and a cron job running close
# together don't hit ESPN twice for the same event.
_cache = {}
_cache_time = {}


def _request(url):
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"[match_summary] request failed: {e}")
        return None


def fetch_summary(league, event_id):
    """Return the raw summary dict for an event, with 2-min caching."""
    key = f"{league}:{event_id}"
    now = datetime.now(timezone.utc)
    if (
        key in _cache
        and key in _cache_time
        and (now - _cache_time[key]).total_seconds() < 120
    ):
        return _cache[key]

    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}"
        f"/summary?event={event_id}"
    )
    data = _request(url)
    if data:
        _cache[key] = data
        _cache_time[key] = now
    return data


def _format_form_line(team_name, last5_entry):
    """Build a one-line summary of a team's last-5-games form.
    Returns e.g. 'نروژ: ۴ برد، ۱ باخت از ۵ بازی اخیر'."""
    if not last5_entry:
        return None
    events = last5_entry.get('events', [])
    if not events:
        return None
    wins = sum(1 for e in events if e.get('gameResult') == 'W')
    draws = sum(1 for e in events if e.get('gameResult') == 'D')
    losses = sum(1 for e in events if e.get('gameResult') == 'L')
    parts = []
    if wins:
        parts.append(f"{wins} برد")
    if draws:
        parts.append(f"{draws} مساوی")
    if losses:
        parts.append(f"{losses} باخت")
    team_fa = fa(team_name, TEAM_FA)
    return f"{team_fa}: " + "، ".join(parts) + f" از {len(events)} بازی اخیر"


def _format_last5_detail(team_name, last5_entry):
    """Build a Persian list of a team's last-5-games results with opponents
    and scores. Used for the 'recent form' bot button."""
    if not last5_entry:
        return []
    events = last5_entry.get('events', [])
    lines = []
    for e in events[:5]:
        opp = e.get('opponent', {}).get('displayName', '')
        opp_fa = fa(opp, TEAM_FA)
        score = e.get('score', '')
        result = e.get('gameResult', '')
        round_name = e.get('roundName', '')
        emoji = {'W': '✅', 'D': '🤝', 'L': '❌'}.get(result, '➖')
        result_fa = {'W': 'برد', 'D': 'مساوی', 'L': 'باخت'}.get(result, result)
        date_str = to_jalali(e.get('gameDate', '') or '') if e.get('gameDate') else ''
        line = f"{emoji} {result_fa} {score} vs {opp_fa}"
        if round_name:
            line += f" ({round_name})"
        if date_str and date_str != (e.get('gameDate', '') or ''):
            # Only append date if conversion succeeded
            line += f" — {date_str.split(' ساعت ')[0]}"
        lines.append(line)
    return lines


def _format_h2h(head_to_head_list):
    """Build a Persian list of head-to-head results between the two teams."""
    if not head_to_head_list:
        return []
    lines = []
    seen_dates = set()
    for entry in head_to_head_list:
        events = entry.get('events', [])
        for e in events:
            d = e.get('gameDate', '')
            if d in seen_dates:
                continue
            seen_dates.add(d)
            opp = e.get('opponent', {}).get('displayName', '')
            opp_fa = fa(opp, TEAM_FA)
            score = e.get('score', '')
            result = e.get('gameResult', '')
            emoji = {'W': '✅', 'D': '🤝', 'L': '❌'}.get(result, '➖')
            year = d[:4] if d else ''
            lines.append(f"{emoji} {score} vs {opp_fa} ({year})")
            if len(lines) >= 5:
                break
    return lines


def _format_leaders(leaders_list):
    """Build a Persian summary of each team's top scorer, assister, and
    shot-taker from the tournament so far."""
    if not leaders_list:
        return []
    lines = []
    for team_entry in leaders_list:
        team = team_entry.get('team', {}).get('displayName', '')
        team_fa = fa(team, TEAM_FA)
        cats = team_entry.get('leaders', [])
        team_lines = []
        for cat in cats:
            cat_name = cat.get('displayName', '')
            cat_fa = {
                'Goals': 'گلزن',
                'Assists': 'پاس گل',
                'Total Shots': 'شوت‌زن',
                'Shots on Target': 'شوت روی هدف',
                'Fouls Committed': 'خطا',
            }.get(cat_name, cat_name)
            leaders = cat.get('leaders', [])
            if not leaders:
                continue
            top = leaders[0]
            athlete = top.get('athlete', {}).get('displayName', '')
            value = top.get('displayValue', '') or top.get('value', '')
            team_lines.append(f"{cat_fa}: {athlete} ({value})")
        if team_lines:
            lines.append(f"• {team_fa} — " + " | ".join(team_lines[:3]))
    return lines


def _format_odds(pickcenter):
    """Build a Persian one-line odds summary if available."""
    if not pickcenter:
        return None
    p = pickcenter[0]
    provider = p.get('provider', {}).get('name', '')
    ou = p.get('overUnder', '')
    draw = p.get('drawOdds', '')
    if isinstance(draw, dict):
        draw_ml = draw.get('moneyLine', '')
    else:
        draw_ml = ''
    parts = []
    if ou:
        parts.append(f"Under/Over: {ou}")
    if draw_ml:
        # Convert American moneyline to a rough implied probability
        try:
            ml = float(draw_ml)
            if ml > 0:
                prob = 100 / (ml + 100) * 100
            else:
                prob = -ml / (-ml + 100) * 100
            parts.append(f"احتمال مساوی: {prob:.0f}%")
        except (ValueError, TypeError):
            pass
    if not parts:
        return None
    return f"📊 {provider}: " + " | ".join(parts)


def build_match_context(summary_data, home_team, away_team):
    """Pull all the useful fields out of a summary response into a single
    Persian-text context block that the AI prompt can include.

    Returns a dict with:
      - form_text:        short form summary for both teams
      - last5_text:       detailed last-5 list per team (joined with \n)
      - h2h_text:         head-to-head history
      - leaders_text:     top scorer/assister per team
      - odds_text:        betting odds line (or None)
      - ai_context:       a compact English-ish text blob for the AI prompt
    """
    if not summary_data:
        return None

    last5 = summary_data.get('lastFiveGames', [])
    h2h = summary_data.get('headToHeadGames', [])
    leaders = summary_data.get('leaders', [])
    pickcenter = summary_data.get('pickcenter', [])

    # Map team name -> last5 entry
    last5_map = {entry.get('team', {}).get('displayName', ''): entry for entry in last5}

    home_form = _format_form_line(home_team, last5_map.get(home_team))
    away_form = _format_form_line(away_team, last5_map.get(away_team))

    form_text = None
    if home_form or away_form:
        form_text = "\n".join([f for f in [home_form, away_form] if f])

    # Detailed last-5 (for the form button, not the AI)
    last5_lines = []
    if home_team in last5_map:
        last5_lines.extend(_format_last5_detail(home_team, last5_map[home_team]))
    if away_team in last5_map:
        if last5_lines:
            last5_lines.append("")
        last5_lines.extend(_format_last5_detail(away_team, last5_map[away_team]))
    last5_text = "\n".join(last5_lines) if last5_lines else None

    h2h_lines = _format_h2h(h2h)
    h2h_text = "\n".join(h2h_lines) if h2h_lines else None

    leaders_lines = _format_leaders(leaders)
    leaders_text = "\n".join(leaders_lines) if leaders_lines else None

    odds_text = _format_odds(pickcenter)

    # Build a compact context blob for the AI prompt - this is what makes
    # the AI analysis current instead of stale. We use a structured format
    # the model can reason about.
    ai_parts = []
    if home_form or away_form:
        ai_parts.append("فرم اخیر در جام جهانی:")
        if home_form:
            ai_parts.append(f"  {home_form}")
        if away_form:
            ai_parts.append(f"  {away_form}")
    if leaders_lines:
        ai_parts.append("برترین‌های جام جهانی:")
        for line in leaders_lines:
            ai_parts.append(f"  {line}")
    if h2h_lines:
        ai_parts.append("تاریخچه‌ی بازی‌های رو در رو:")
        for line in h2h_lines[:3]:
            ai_parts.append(f"  {line}")
    if odds_text:
        ai_parts.append(f"پیش‌بینی بنگاه‌های شرط‌بندی: {odds_text}")
    ai_context = "\n".join(ai_parts) if ai_parts else None

    return {
        'form_text': form_text,
        'last5_text': last5_text,
        'h2h_text': h2h_text,
        'leaders_text': leaders_text,
        'odds_text': odds_text,
        'ai_context': ai_context,
    }
