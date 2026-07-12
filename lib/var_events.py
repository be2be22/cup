"""
VAR (Video Assistant Referee) event detector and video fetcher.

ESPN's commentary feed includes entries like:
  - "GOAL OVERTURNED BY VAR: Player scores but the goal is ruled out after a VAR review."
  - "VAR Decision: No Penalty England."
  - "VAR Decision: No Goal Norway 1-1 England."
  - "Penalty confirmed after VAR review."

When we detect a new VAR event, we:
  1. Send a text alert to the channel immediately
  2. Wait 90 seconds (like we do for goals)
  3. Search Reddit r/soccer for a video clip of the VAR event
  4. Send the video to the channel

We track which VAR events we've already processed in state.json under
'var_events_sent' (a list of minute strings) so we don't re-send.
"""
import re
import time

from lib.api_client import _load_league
from lib.match_summary import fetch_summary
from lib.formatter import fa, TEAM_FA, PLAYER_FA, get_flag, SEP
from lib.telegram_sender import send_message, send_video
from lib.state_manager import get_match_state, update_match_state
from lib.reddit_video import fetch_reddit_key_moment_video


# Regex patterns to detect VAR-related commentary entries.
# These match the typical phrasing ESPN uses for VAR events.
_VAR_PATTERNS = [
    re.compile(r'GOAL OVERTURNED BY VAR', re.IGNORECASE),
    re.compile(r'VAR Decision', re.IGNORECASE),
    re.compile(r'VAR review', re.IGNORECASE),
    re.compile(r'penalty.*VAR', re.IGNORECASE),
    re.compile(r'VAR.*penalty', re.IGNORECASE),
    re.compile(r'overturned by VAR', re.IGNORECASE),
    re.compile(r'pitchside monitor', re.IGNORECASE),
    re.compile(r'after a VAR', re.IGNORECASE),
]


def _is_var_event(text):
    """Return True if the commentary text describes a VAR event."""
    if not text:
        return False
    for pattern in _VAR_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _extract_var_description(text, home_team, away_team, commentary=None):
    """Build a short Persian description of the VAR event from the
    English commentary text.

    Returns a dict with:
      - 'type': 'goal_overturned', 'penalty_awarded', 'penalty_denied', 'no_goal', 'card_changed', 'general'
      - 'description_fa': Persian description for the alert message
      - 'search_query': English search query for Reddit (e.g., 'VAR England penalty')
      - 'team': which team the event is about (may be None)
      - 'player': which player (extracted from nearby commentary for card_changed)
    """
    text_lower = text.lower()

    # Determine the type of VAR event
    if 'goal overturned' in text_lower or 'ruled out' in text_lower:
        event_type = 'goal_overturned'
        description_fa = 'گل توسط VAR رد شد'
    elif 'no penalty' in text_lower:
        event_type = 'penalty_denied'
        description_fa = 'پنالتی توسط VAR رد شد'
    elif 'penalty confirmed' in text_lower or 'penalty awarded' in text_lower:
        event_type = 'penalty_awarded'
        description_fa = 'پنالتی توسط VAR تأیید شد'
    elif 'no goal' in text_lower:
        event_type = 'no_goal'
        description_fa = 'گل‌نشدن توسط VAR تأیید شد'
    elif 'card changed' in text_lower:
        event_type = 'card_changed'
        description_fa = 'تغییر کارت توسط VAR'
    else:
        event_type = 'general'
        description_fa = 'تصمیم VAR'

    # Try to identify which team the VAR event is about
    team_mentioned = None
    for team in [home_team, away_team]:
        if team.lower() in text_lower:
            team_mentioned = team
            break

    # For 'card_changed', try to find the player from the NEXT
    # commentary entry (ESPN usually follows "VAR Decision: Card Changed"
    # with "Second yellow card to Player (Team)" or "Red card to Player")
    player = None
    if event_type == 'card_changed' and commentary:
        # Find the VAR entry's position in commentary
        for i, c in enumerate(commentary):
            if c.get('text', '') == text:
                # Look at the next 1-3 entries for card details
                for j in range(i + 1, min(i + 4, len(commentary))):
                    next_text = commentary[j].get('text', '') or ''
                    # Look for "yellow card to PlayerName (TeamName)" or "red card to..."
                    import re
                    card_match = re.search(
                        r'(?:second yellow card|red card) to ([^(]+)\s*\(([^)]+)\)',
                        next_text, re.IGNORECASE,
                    )
                    if card_match:
                        player = card_match.group(1).strip()
                        team_name = card_match.group(2).strip()
                        # Match team_name to home/away
                        for team in [home_team, away_team]:
                            if team.lower() == team_name.lower():
                                team_mentioned = team
                                break
                        # Update description
                        if 'second yellow' in next_text.lower():
                            description_fa = 'کارت زرد دوم (و قرمز) توسط VAR'
                        elif 'red card' in next_text.lower():
                            description_fa = 'کارت قرمز توسط VAR'
                        break
                break

    # Build the search query for Reddit
    # r/soccer VAR posts look like: "England penalty overturned by VAR 103'"
    # or "VAR: No goal Norway 55'"
    query_parts = ['VAR']
    if team_mentioned:
        query_parts.append(team_mentioned)
    if event_type == 'penalty_denied':
        query_parts.append('penalty')
    elif event_type == 'penalty_awarded':
        query_parts.append('penalty')
    elif event_type == 'goal_overturned' or event_type == 'no_goal':
        query_parts.append('goal')
    
    return {
        'type': event_type,
        'description_fa': description_fa,
        'search_query': ' '.join(query_parts),
        'team': team_mentioned,
        'player': player,
    }


def check_var_events(match):
    """Scan ESPN commentary for VAR events and process any new ones.
    
    For each new VAR event:
      1. Send a text alert immediately
      2. Queue it for video search (with 90s delay, same as goals)
    
    Returns the list of VAR events that need video search (for the
    caller to process on subsequent runs).
    """
    match_id = str(match['id'])
    
    try:
        league = _load_league()
        summary = fetch_summary(league, match['id'])
        if not summary:
            return
        commentary = summary.get('commentary', []) or []
    except Exception as e:
        print(f"[var_events] fetch failed: {e}")
        return
    
    state = get_match_state(match_id)
    var_sent = state.get('var_events_sent', []) or []
    var_pending = state.get('var_events_pending', []) or []
    var_detect_times = state.get('var_detect_times', {}) or {}
    
    now_ts = time.time()
    new_events = []
    
    for c in commentary:
        text = c.get('text', '') or ''
        if not _is_var_event(text):
            continue
        
        minute = c.get('time', {}).get('displayValue', '') or ''
        # Use minute+text snippet as the unique key
        text_snippet = text[:50].replace(' ', '_')
        event_key = f"var_{minute}_{text_snippet}"
        
        if event_key in var_sent or event_key in var_pending:
            continue
        
        # New VAR event detected!
        var_info = _extract_var_description(text, match['home_team'], match['away_team'], commentary)

        # Send the text alert immediately
        home_fa = fa(match['home_team'], TEAM_FA)
        away_fa = fa(match['away_team'], TEAM_FA)
        score = f"{match['home_score']} - {match['away_score']}"

        emoji = '📺'  # VAR emoji
        team_str = ''
        if var_info['team']:
            team_fa = fa(var_info['team'], TEAM_FA)
            team_str = f' | {get_flag(var_info["team"])} {team_fa}'

        player_str = ''
        if var_info.get('player'):
            player_fa = fa(var_info['player'], PLAYER_FA)
            player_str = f'\n👤 بازیکن: {player_fa}'

        msg = (
            f"\n{emoji} *تصمیم VAR*\n{SEP}\n"
            f"⏱️ دقیقه {minute}{team_str}\n"
            f"📋 {var_info['description_fa']}{player_str}\n"
            f"⚽ {get_flag(match['home_team'])} {home_fa}  {score}  {away_fa} {get_flag(match['away_team'])}\n"
            f"{SEP}"
        ).strip()
        
        if send_message(msg):
            print(f"[var_events] alert sent: {var_info['description_fa']} at {minute}")
        
        # Queue for video search
        var_pending.append(event_key)
        var_detect_times[event_key] = now_ts
        # Store the VAR info for the video search
        if 'var_events_info' not in state:
            state['var_events_info'] = {}
        state['var_events_info'][event_key] = {
            'minute': minute,
            'search_query': var_info['search_query'],
            'team': var_info['team'],
            'description_fa': var_info['description_fa'],
        }
        new_events.append(event_key)
    
    # Save state
    update_match_state(match_id,
        var_events_sent=var_sent,
        var_events_pending=var_pending,
        var_detect_times=var_detect_times,
        var_events_info=state.get('var_events_info', {}),
    )
    
    return new_events


def process_pending_var_videos(match):
    """Search Reddit for video clips of pending VAR events and send them.
    
    Called by event_monitor.py on each cron run. Uses the same 90-second
    delay as goal videos to give r/soccer users time to post the clip.
    """
    match_id = str(match['id'])
    state = get_match_state(match_id)
    
    var_pending = state.get('var_events_pending', []) or []
    var_sent = state.get('var_events_sent', []) or []
    var_detect_times = state.get('var_detect_times', {}) or {}
    var_events_info = state.get('var_events_info', {}) or {}
    
    if not var_pending:
        return
    
    now_ts = time.time()
    still_pending = []
    
    for event_key in var_pending:
        if event_key in var_sent:
            continue
        
        # Check the 90-second delay
        detect_time = var_detect_times.get(event_key, now_ts)
        seconds_since = now_ts - detect_time
        if seconds_since < 90:
            print(f"[var_events] {event_key}: waiting {90-seconds_since:.0f}s before Reddit search")
            still_pending.append(event_key)
            continue
        
        # Get the VAR info
        var_info = var_events_info.get(event_key, {})
        if not var_info:
            var_sent.append(event_key)
            continue
        
        search_query = var_info.get('search_query', 'VAR')
        minute = var_info.get('minute', '')
        team = var_info.get('team', '')
        description_fa = var_info.get('description_fa', 'تصمیم VAR')
        
        # Search Reddit for the VAR clip
        # We use fetch_reddit_key_moment_video with the search query
        video_url, video_title = fetch_reddit_key_moment_video(
            moment_type='VAR',
            player_name=team or '',  # use team name as the "player" for matching
            minute_str=minute,
            home_team=match['home_team'],
            away_team=match['away_team'],
        )
        
        if video_url:
            # Send the video
            team_fa = fa(team, TEAM_FA) if team else ''
            caption_parts = [
                f"📺 ویدیوی تصمیم VAR",
                f"⏱️ دقیقه {minute}",
            ]
            if team:
                caption_parts.append(f"📋 {description_fa} - {get_flag(team)} {team_fa}")
            else:
                caption_parts.append(f"📋 {description_fa}")
            caption_parts.append(
                f"📊 {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
                f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}"
            )
            caption = "\n".join(caption_parts)
            
            if send_video(video_url, caption=caption):
                var_sent.append(event_key)
                print(f"[var_events] video sent for {event_key}")
            else:
                var_sent.append(event_key)
                print(f"[var_events] video send failed for {event_key}")
        else:
            # No clip found yet - keep pending for a few more attempts
            # (limit to ~10 minutes = 10 cron runs)
            if seconds_since < 600:
                still_pending.append(event_key)
            else:
                # Give up after 10 minutes
                var_sent.append(event_key)
                print(f"[var_events] giving up on {event_key} after 10 minutes")
    
    update_match_state(match_id,
        var_events_pending=still_pending,
        var_events_sent=var_sent,
    )
