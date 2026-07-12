#!/usr/bin/env python3
"""
Pre-match notification system.

Sends THREE types of pre-match messages:

1. EARLY NOTICE (when ESPN first reports the match as 'pre')
   - Basic fixture info: teams, date, venue, stage
   - Sent as soon as the match appears in the ESPN feed
   - Helps users know about upcoming matches in advance

2. 30-MINUTE WARNING (30 min before kickoff)
   - Full AI analysis with live ESPN context (form, H2H, leaders)
   - Includes the predicted lineups if available from SportScore
   - This is the 'main' pre-match message most users care about

3. LINEUP ANNOUNCEMENT (when teams are announced, usually ~60 min before)
   - Starting XIs with formation for both teams
   - Fetched from SportScore (ESPN's roster data is empty)

Each message is tracked separately in state.json so we don't re-send:
  - prematch_early_sent:     bool
  - prematch_30min_sent:     bool
  - prematch_lineup_sent:    bool
"""
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA, get_flag, SEP, to_jalali
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state
from lib.analysis_builder import build_analysis


def _parse_match_date(match):
    """Parse the match date string into a timezone-aware datetime."""
    try:
        return datetime.fromisoformat(match.get('date', '').replace('Z', '+00:00'))
    except Exception:
        return None


def _minutes_until_kickoff(match):
    """Return the number of minutes until kickoff, or None if we can't
    parse the match date. Negative if the match has already started."""
    dt = _parse_match_date(match)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return int((dt - now).total_seconds() / 60)


def _send_early_notice(match):
    """Send the early fixture notice (as soon as ESPN reports the match)."""
    stage = match.get('stage', '') or 'جام جهانی ۲۰۲۶'
    venue_parts = [p for p in [match.get('venue', ''), match.get('venue_city', '')] if p]
    venue = '، '.join(venue_parts)

    hf = fa(match['home_team'], TEAM_FA)
    af = fa(match['away_team'], TEAM_FA)
    time_str = to_jalali(match.get('date', ''))

    msg = (
        f"📅 *بازی پیش‌رو*\n{SEP}\n"
        f"{get_flag(match['home_team'])} *{hf}* 🆚 *{af}* {get_flag(match['away_team'])}\n"
        f"{SEP}\n"
        f"🏆 {stage}\n"
        f"🕐 {time_str}\n"
        f"🏟️ {venue}\n"
        f"{SEP}\n"
        f"⏰ ۳۰ دقیقه قبل از شروع، تحلیل کامل رو می‌فرستیم"
    ).strip()
    return send_message(msg)


def _send_30min_analysis(match):
    """Send the full AI analysis 30 minutes before kickoff."""
    stage = match.get('stage', '') or 'جام جهانی ۲۰۲۶'
    venue_parts = [p for p in [match.get('venue', ''), match.get('venue_city', '')] if p]
    venue = '، '.join(venue_parts)

    # Build the AI analysis with live ESPN context
    analysis = build_analysis(
        match['home_team'], match['away_team'],
        stage=stage, venue=venue, group='',
        event_id=match.get('id'),
    )

    # Try to get lineups from SportScore (may not be available yet)
    lineup_text = _try_get_lineup_text(match)

    # Build the message
    fmt = PersianFormatter()
    msg = fmt.format_prematch({
        'home_team': match['home_team'],
        'away_team': match['away_team'],
        'time': match.get('date', ''),
        'venue': venue,
        'stage': stage,
    }, analysis)

    # Add lineup section if available
    if lineup_text:
        msg += f"\n\n{lineup_text}"

    msg += f"\n\n⏰ *۳۰ دقیقه تا شروع بازی!*"
    return send_message(msg)


def _try_get_lineup_text(match):
    """Try to fetch lineups from SportScore. Returns a formatted string
    or None if not available yet (teams usually announce ~60 min before)."""
    try:
        from lib.sportscore_client import get_lineups, find_match_slug
        slug1 = find_match_slug(match['home_team'], match['away_team'])
        slug2 = find_match_slug(match['away_team'], match['home_team'])

        home_lineup, away_lineup = get_lineups(slug1)
        if not home_lineup:
            home_lineup, away_lineup = get_lineups(slug2)
            if home_lineup:
                home_lineup, away_lineup = away_lineup, home_lineup

        if not home_lineup and not away_lineup:
            return None

        lines = [f"📋 *ترکیب‌های اولیه*\n{SEP}"]

        def format_side(lineup, team_name):
            if not lineup:
                return None
            formation = lineup.get('formation', '') if isinstance(lineup, dict) else ''
            players = lineup.get('players', []) if isinstance(lineup, dict) else []
            if not players:
                return None
            team_fa = fa(team_name, TEAM_FA)
            result = [f"\n{get_flag(team_name)} *{team_fa}*"]
            if formation:
                result.append(f"الگوی بازی: {formation}")
            for p in players:
                if isinstance(p, dict):
                    name = p.get('name', '') or p.get('player', '')
                    pos = p.get('position', '') or p.get('pos', '')
                    num = p.get('number', '') or p.get('shirt', '')
                    name_fa = fa(name, PLAYER_FA)
                    if num:
                        result.append(f"  {num}. {name_fa} ({pos})")
                    else:
                        result.append(f"  • {name_fa} ({pos})")
            return "\n".join(result)

        home_text = format_side(home_lineup, match['home_team'])
        away_text = format_side(away_lineup, match['away_team'])
        if home_text:
            lines.append(home_text)
        if away_text:
            lines.append(away_text)
        lines.append(SEP)
        return "\n".join(lines)
    except Exception as e:
        print(f"[prematch] lineup fetch failed: {e}")
        return None


def _send_lineup_announcement(match):
    """Send a lineup announcement when teams are first announced.
    Called when we detect that lineups are now available from SportScore."""
    lineup_text = _try_get_lineup_text(match)
    if not lineup_text:
        return False

    hf = fa(match['home_team'], TEAM_FA)
    af = fa(match['away_team'], TEAM_FA)
    header = (
        f"📋 *ترکیب‌ها اعلام شد*\n{SEP}\n"
        f"{get_flag(match['home_team'])} *{hf}* 🆚 *{af}* {get_flag(match['away_team'])}\n{SEP}\n"
    )
    msg = f"{header}\n{lineup_text}"
    return send_message(msg)


def main(match_id=None):
    client = FootballAPIClient()

    for event in client.get_all_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if match['status_state'] != 'pre':
            continue

        state = get_match_state(str(match['id']))
        minutes_to_kickoff = _minutes_until_kickoff(match)

        if minutes_to_kickoff is None:
            continue  # can't parse date, skip

        # ============================================================
        # 1. EARLY NOTICE (sent as soon as ESPN reports the match)
        # ============================================================
        if not state.get('prematch_early_sent'):
            if _send_early_notice(match):
                update_match_state(str(match['id']), prematch_early_sent=True)
                print(f"[prematch] early notice sent for {match['home_team']} vs {match['away_team']} ({minutes_to_kickoff} min to kickoff)")

        # ============================================================
        # 2. LINEUP ANNOUNCEMENT (when teams are announced, ~60 min before)
        #    We start checking for lineups when we're within 90 minutes
        #    of kickoff, and send the announcement as soon as lineups
        #    become available.
        # ============================================================
        if not state.get('prematch_lineup_sent') and minutes_to_kickoff <= 90:
            try:
                if _send_lineup_announcement(match):
                    update_match_state(str(match['id']), prematch_lineup_sent=True)
                    print(f"[prematch] lineup sent for {match['home_team']} vs {match['away_team']} ({minutes_to_kickoff} min to kickoff)")
            except Exception as e:
                print(f"[prematch] lineup check failed: {e}")

        # ============================================================
        # 3. 30-MINUTE WARNING (the main pre-match analysis)
        # ============================================================
        if not state.get('prematch_30min_sent'):
            if minutes_to_kickoff <= 30 and minutes_to_kickoff >= -5:
                # Send 30 min before, or up to 5 min after (in case we
                # missed the exact 30-min mark due to cron timing)
                if _send_30min_analysis(match):
                    update_match_state(str(match['id']), prematch_30min_sent=True)
                    print(f"[prematch] 30-min analysis sent for {match['home_team']} vs {match['away_team']} ({minutes_to_kickoff} min to kickoff)")

        # ============================================================
        # Legacy: also set 'prematch_sent' for backward compat
        # ============================================================
        if state.get('prematch_30min_sent') and not state.get('prematch_sent'):
            update_match_state(str(match['id']), prematch_sent=True)


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
