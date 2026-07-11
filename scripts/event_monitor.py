#!/usr/bin/env python3
"""Checks live matches for new goals, cards, substitutions, and special
alerts (hat-tricks, comebacks, star substitutions) since the last run.

When a new goal is detected, after sending the text goal message it
also searches r/soccer for a fan-posted v.redd.it clip and forwards
the matching .mp4 URL to the channel via Telegram's sendVideo.

Special alerts:
  - Hat-trick 🎩: when a player scores their 3rd+ goal
  - Comeback 🔄: when a team that was trailing by 2+ equalizes or leads
  - Star sub 👤: when a star player (see lib/star_players.py) is subbed

NO video data is ever stored on disk - we only pass the .mp4 URL to
Telegram's sendVideo API.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
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
        last_subs = state.get('last_subs', [])  # list of "out|in|minute" strings

        # Check for comeback (compare current score to previous)
        check_comeback(match, state)

        # 1. Send new goal/card text messages + check hat-trick
        for g in match['goals']:
            event_key = f"goal_{g['player']}_{g['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_goal({
                    'team': g['team'], 'player': g['player'], 'minute': g['minute'],
                    'home_score': match['home_score'], 'away_score': match['away_score'],
                    'home_team': match['home_team'], 'away_team': match['away_team'],
                }))
                last_events.append(event_key)
                # Queue for video lookup
                if event_key not in video_pending and event_key not in video_sent:
                    video_pending.append(event_key)
                # Check for hat-trick AFTER sending the goal message
                check_hat_trick(match, g['player'], g['team'])

        for c in match['cards']:
            event_key = f"card_{c['player']}_{c['minute']}"
            if event_key not in last_events:
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

        # 2. Check for new substitutions + star player alerts
        for s in match.get('substitutions', []):
            sub_key = f"{s.get('out','')}|{s.get('in','')}|{s.get('minute','')}"
            if sub_key not in last_subs:
                last_subs.append(sub_key)
                # Check if this involves a star player (sends special alert)
                is_star = check_star_substitution(match, s)
                if not is_star:
                    # Regular substitution - only report if it's notable
                    # (we don't report every sub to avoid spam)
                    pass

        # 3. Try to fetch and send videos for any pending goals (Reddit only)
        still_pending = []
        for event_key in video_pending:
            if event_key in video_sent:
                continue
            player_name = None
            minute_str = None
            goal_team = None
            for g in match['goals']:
                if f"goal_{g['player']}_{g['minute']}" == event_key:
                    player_name = g['player']
                    minute_str = g['minute']
                    goal_team = g['team']
                    break

            if not player_name:
                video_sent.append(event_key)
                continue

            video_url, video_title = fetch_reddit_goal_video(
                player_name, minute_str,
                match['home_team'], match['away_team'],
            )

            if video_url:
                player_fa = fa(player_name, PLAYER_FA)
                team_fa = fa(goal_team, TEAM_FA)
                caption = (
                    f"🎥 ویدیوی گلِ {player_fa} ({team_fa}) - دقیقه {minute_str}\n"
                    f"📊 {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
                    f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}"
                )
                if send_video(video_url, caption=caption):
                    video_sent.append(event_key)
                    print(f"Video sent for goal: {player_name} ({minute_str}) via Reddit")
                else:
                    video_sent.append(event_key)
                    print(f"Video send failed for goal: {player_name} ({minute_str})")
            else:
                still_pending.append(event_key)

        # Update state
        update_match_state(
            str(match['id']),
            last_events=last_events[-100:],
            video_pending=still_pending,
            video_sent=video_sent[-50:],
            last_subs=last_subs[-50:],
        )

    print(f"Event check completed at {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
