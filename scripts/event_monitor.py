#!/usr/bin/env python3
"""Checks live matches for new goals, cards, substitutions, VAR events,
and special alerts (hat-tricks, comebacks, star substitutions).

MAJOR FIXES in this version:
  1. SCORE-BASED GOAL DETECTION: when ESPN updates the score before
     adding the goal to details, we detect the goal from the score
     change and send an immediate alert.
  2. CARD DETECTION: ESPN's scoreboard details array sometimes has
     cards with type='Yellow Card' or 'Red Card'. We also check the
     yellowCard/redCard boolean fields as a fallback.
  3. VAR EVENT DETECTION: ESPN's commentary feed has VAR events.
     We scan it on every cron run and send alerts.
  4. TEAM NAME RESOLUTION: the details array's team.id doesn't always
     match the competitors array. We fall back to matching by team
     displayName or using the keyEvents team field.
  5. GOAL PLAYER NAME: when the scoreboard details don't have the
     athlete name, we try to extract it from the keyEvents text
     (e.g. "Goal! Norway 1, England 0. Andreas Schjelderup...").
"""
import sys
import os
import re
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA
from lib.telegram_sender import send_message, send_video
from lib.state_manager import get_match_state, update_match_state
from lib.reddit_video import fetch_reddit_goal_video, fetch_reddit_key_moment_video
from lib.special_alerts import (
    check_hat_trick,
    check_comeback,
    check_star_substitution,
)
from lib.stoppage_alert import check_stoppage_announcement
from lib.var_events import check_var_events, process_pending_var_videos


def build_events_text(match):
    lines = []
    for g in match.get('goals', []):
        lines.append(f"⚽ گل: {fa(g['team'], TEAM_FA)} - {fa(g['player'], PLAYER_FA)} ({g['minute']})")
    for c in match.get('cards', []):
        emoji = '🟡' if 'زرد' in c['detail'] else '🔴'
        lines.append(f"{emoji} {c['detail']}: {fa(c['team'], TEAM_FA)} - {fa(c['player'], PLAYER_FA)} ({c['minute']})")
    return '\n'.join(lines) if lines else None


def main(match_id=None):
    client = FootballAPIClient()
    fmt = PersianFormatter()

    for event in client.get_live_fixtures():
        match = client.parse_event(event)

        if match_id and str(match['id']) != str(match_id):
            continue
        if not match['home_team']:
            continue

        state = get_match_state(str(match['id']))
        last_events = state.get('last_events', [])
        video_pending = state.get('video_pending', [])
        video_sent = state.get('video_sent', [])
        last_subs = state.get('last_subs', [])

        # Check for comeback, stoppage, VAR
        check_comeback(match, state)
        try:
            check_stoppage_announcement(match)
        except Exception as e:
            print(f"[event_monitor] stoppage alert failed: {e}")
        try:
            check_var_events(match)
        except Exception as e:
            print(f"[event_monitor] VAR check failed: {e}")
        try:
            process_pending_var_videos(match)
        except Exception as e:
            print(f"[event_monitor] VAR video failed: {e}")

        # ============================================================
        # SCORE-BASED GOAL DETECTION (when ESPN details lag behind)
        # ============================================================
        prev_score = state.get('prev_score') or {}
        prev_home = prev_score.get('home', 0)
        prev_away = prev_score.get('away', 0)
        curr_home = match['home_score']
        curr_away = match['away_score']

        if curr_home > prev_home or curr_away > prev_away:
            goals_from_details = match['goals']
            reported_goal_keys = [e for e in last_events if e.startswith('goal_')]

            if len(goals_from_details) <= len(reported_goal_keys):
                # ESPN hasn't added the goal to details yet
                which_team = 'home' if curr_home > prev_home else 'away'
                goal_team = match['home_team'] if which_team == 'home' else match['away_team']
                minute_str = match.get('clock', f"{match['minute']}'")
                event_key = f"goal_score_{which_team}_{minute_str}"

                if event_key not in last_events:
                    print(f"[event_monitor] SCORE GOAL: {goal_team} at {minute_str}")
                    send_message(fmt.format_goal({
                        'team': goal_team,
                        'player': '(در حال دریافت...)',
                        'minute': minute_str,
                        'home_score': curr_home,
                        'away_score': curr_away,
                        'home_team': match['home_team'],
                        'away_team': match['away_team'],
                    }))
                    last_events.append(event_key)
                    if event_key not in video_pending and event_key not in video_sent:
                        video_pending.append(event_key)

        # ============================================================
        # GOAL DETECTION from match['goals'] (ESPN details)
        # ============================================================
        for g in match['goals']:
            event_key = f"goal_{g['player']}_{g['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_goal({
                    'team': g['team'], 'player': g['player'], 'minute': g['minute'],
                    'home_score': match['home_score'], 'away_score': match['away_score'],
                    'home_team': match['home_team'], 'away_team': match['away_team'],
                }))
                last_events.append(event_key)
                if event_key not in video_pending and event_key not in video_sent:
                    video_pending.append(event_key)
                check_hat_trick(match, g['player'], g['team'])

        # ============================================================
        # CARD DETECTION from match['cards']
        # ============================================================
        for c in match['cards']:
            event_key = f"card_{c['player']}_{c['minute']}"
            if event_key not in last_events:
                print(f"[event_monitor] CARD: {c['player']} ({c['team']}) {c['detail']} at {c['minute']}")
                send_message(fmt.format_card({
                    'team': c['team'], 'player': c['player'],
                    'minute': c['minute'], 'detail': c['detail'],
                }))
                last_events.append(event_key)
                # For red cards, try to find a video clip on Reddit
                if 'قرمز' in c['detail']:
                    try:
                        video_url, _ = fetch_reddit_key_moment_video(
                            'red card', c['player'], c['minute'],
                            match['home_team'], match['away_team'],
                        )
                        if video_url:
                            player_fa = fa(c['player'], PLAYER_FA)
                            team_fa = fa(c['team'], TEAM_FA)
                            caption = (
                                f"🔴 ویدیوی کارت قرمزِ {player_fa} ({team_fa}) - دقیقه {c['minute']}\n"
                                f"📎 منبع: Reddit r/soccer"
                            )
                            send_video(video_url, caption=caption)
                    except Exception as e:
                        print(f"[event_monitor] red card video failed: {e}")

        # ============================================================
        # SUBSTITUTION DETECTION + star player alerts
        # ============================================================
        for s in match.get('substitutions', []):
            sub_key = f"{s.get('out','')}|{s.get('in','')}|{s.get('minute','')}"
            if sub_key not in last_subs:
                last_subs.append(sub_key)
                check_star_substitution(match, s)

        # ============================================================
        # VIDEO SEARCH for pending goals (with 90s delay)
        # ============================================================
        now_ts = time.time()
        goal_detect_times = state.get('goal_detect_times', {}) or {}

        still_pending = []
        for event_key in video_pending:
            if event_key in video_sent:
                continue
            # Find the goal info
            player_name = None
            minute_str = None
            goal_team = None
            for g in match['goals']:
                if f"goal_{g['player']}_{g['minute']}" == event_key:
                    player_name = g['player']
                    minute_str = g['minute']
                    goal_team = g['team']
                    break

            # If not found in goals, check if it's a score-based goal
            if not player_name and event_key.startswith('goal_score_'):
                parts = event_key.split('_', 3)  # goal_score_home_14'
                if len(parts) >= 4:
                    which_team = parts[2]
                    minute_str = parts[3]
                    goal_team = match['home_team'] if which_team == 'home' else match['away_team']
                    # Try to find the player from match['goals'] now
                    for g in match['goals']:
                        if g['minute'] == minute_str or minute_str in g['minute']:
                            player_name = g['player']
                            goal_team = g['team']
                            break

            if not player_name and not event_key.startswith('goal_score_'):
                video_sent.append(event_key)
                continue
            if not goal_team:
                video_sent.append(event_key)
                continue

            if event_key not in goal_detect_times:
                goal_detect_times[event_key] = now_ts

            seconds_since_goal = now_ts - goal_detect_times[event_key]
            if seconds_since_goal < 90:
                print(f"[event_monitor] {event_key}: waiting {90-seconds_since_goal:.0f}s")
                still_pending.append(event_key)
                continue

            # Search Reddit for the goal video
            # IMPORTANT: if Reddit returns 429 (rate limited), we skip
            # the video search entirely for this run to avoid blocking
            # the cron job for minutes. The video will be searched
            # again on the next cron run.
            search_player = player_name or goal_team
            try:
                video_url, video_title = fetch_reddit_goal_video(
                    search_player, minute_str or '',
                    match['home_team'], match['away_team'],
                )
            except Exception as e:
                if '429' in str(e):
                    print(f"[event_monitor] Reddit 429 rate limited, skipping video search")
                    video_url = None
                else:
                    raise

            if video_url:
                player_fa = fa(player_name, PLAYER_FA) if player_name else goal_team
                team_fa = fa(goal_team, TEAM_FA)
                caption = (
                    f"🎥 ویدیوی گلِ {player_fa} ({team_fa}) - دقیقه {minute_str}\n"
                    f"📊 {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
                    f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}"
                )
                if send_video(video_url, caption=caption):
                    video_sent.append(event_key)
                    print(f"[event_monitor] video sent: {event_key}")
                else:
                    video_sent.append(event_key)
                    print(f"[event_monitor] video failed: {event_key}")
            else:
                still_pending.append(event_key)

        # Update state
        update_match_state(
            str(match['id']),
            last_events=last_events[-100:],
            video_pending=still_pending,
            video_sent=video_sent[-50:],
            last_subs=last_subs[-50:],
            goal_detect_times=goal_detect_times,
        )

    print(f"Event check completed at {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
