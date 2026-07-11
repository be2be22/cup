"""
Stoppage time announcement detector.

ESPN's commentary feed includes entries like:
  [45'] Fourth official has announced 5 minutes of added time.
  [90'+1'] Fourth official has announced 7 minutes of added time.

This module scans the commentary for these announcements and sends a
special alert to the channel when a new stoppage time is announced.

We track which announcements we've already sent in state.json under
'stoppage_announced' (a list of minute strings like '45', '90') so we
don't re-send the same announcement on subsequent cron runs.
"""
import re

from lib.api_client import FootballAPIClient, _load_league
from lib.match_summary import fetch_summary
from lib.formatter import fa, TEAM_FA, get_flag, SEP
from lib.telegram_sender import send_message
from lib.state_manager import get_match_state, update_match_state


# Regex to match ESPN's stoppage time announcement.
# Examples:
#   "Fourth official has announced 5 minutes of added time."
#   "Fourth official has announced 7 minutes of added time."
#   "5 minutes of added time has been announced."
_STOPPAGE_PATTERN = re.compile(
    r'(\d+)\s+minut(?:e|es)\s+of\s+(?:added|stoppage|additional|injury)\s+time',
    re.IGNORECASE,
)


def _detect_stoppage_announcement(commentary_entries):
    """Scan commentary entries for a stoppage time announcement.
    Returns (minute_str, num_minutes) if found, else None.

    minute_str is the minute at which the announcement was made (e.g.
    '45' or '90'), num_minutes is the number of added minutes (e.g. 5).
    """
    for entry in commentary_entries:
        text = entry.get('text', '') or ''
        match = _STOPPAGE_PATTERN.search(text)
        if match:
            num_minutes = int(match.group(1))
            minute_str = entry.get('minute', '') or ''
            # Extract the base minute (e.g. '45' from "45'")
            base_minute = minute_str.split("'")[0].split("+")[0]
            return base_minute, num_minutes
    return None


def check_stoppage_announcement(match):
    """Check if a stoppage time announcement has been made for this
    match that we haven't yet reported. If so, send a special alert.

    Returns True if an alert was sent, False otherwise.
    """
    match_id = str(match['id'])

    # Fetch the commentary feed
    try:
        league = _load_league()
        summary = fetch_summary(league, match['id'])
        if not summary:
            return False
        commentary = summary.get('commentary', []) or []
    except Exception as e:
        print(f"[stoppage_alert] fetch failed: {e}")
        return False

    # Convert commentary to the format our detector expects
    entries = []
    for c in commentary:
        time_obj = c.get('time', {}) or {}
        entries.append({
            'minute': time_obj.get('displayValue', '') or '',
            'text': c.get('text', '') or '',
        })

    result = _detect_stoppage_announcement(entries)
    if not result:
        return False

    base_minute, num_minutes = result

    # Check if we already sent this announcement
    state = get_match_state(match_id)
    sent = state.get('stoppage_announced', []) or []
    # Use a key like "45_5" (minute + num_minutes) to avoid duplicates
    alert_key = f"{base_minute}_{num_minutes}"
    if alert_key in sent:
        return False

    # Send the alert
    home_fa = fa(match['home_team'], TEAM_FA)
    away_fa = fa(match['away_team'], TEAM_FA)
    score = f"{match['home_score']} - {match['away_score']}"

    # Determine which half this stoppage time is for
    if base_minute == '45' or int(base_minute) <= 45:
        half_label = "پایان نیمه‌ی اول"
        emoji = "⏱️"
    elif base_minute == '90' or int(base_minute) >= 90:
        half_label = "پایان وقت قانونی"
        emoji = "⏰"
    else:
        half_label = f"دقیقه {base_minute}"
        emoji = "⏱️"

    # Convert number to Persian digits
    persian_num = str(num_minutes).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

    msg = (
        f"\n{emoji} *اعلام وقت اضافه*\n{SEP}\n"
        f"⏱️ *{persian_num} دقیقه وقت اضافه* برای {half_label} اعلام شد!\n"
        f"⚽ {get_flag(match['home_team'])} {home_fa}  {score}  {away_fa} {get_flag(match['away_team'])}\n"
        f"{SEP}"
    ).strip()

    if send_message(msg):
        sent.append(alert_key)
        # Keep the list bounded
        update_match_state(match_id, stoppage_announced=sent[-20:])
        print(f"[stoppage_alert] sent: {num_minutes} minutes at {base_minute}' for match {match_id}")
        return True
    return False
