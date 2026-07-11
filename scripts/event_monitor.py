#!/usr/bin/env python3
"""Checks live matches for new goals and cards since the last run.

When a new goal is detected, after sending the text goal message it
also searches r/soccer for a fan-posted v.redd.it clip and forwards
the matching .mp4 URL to the channel via Telegram's sendVideo.

Important: NO video data is ever stored on the server's disk. We only
ever hold the .mp4 URL string in memory and pass it to Telegram's
sendVideo API, which causes Telegram's servers to download the video
directly from v.redd.it. Once sendVideo returns, we drop the URL and
keep only the event_key string ('goal_<player>_<minute>') in
state.json so we don't re-send the same clip.

The video lookup is retried across the next few cron runs (each run is
~1 minute apart) because Reddit posts typically appear 1-3 minutes
after the goal is scored.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA
from lib.telegram_sender import send_message, send_video
from lib.state_manager import get_match_state, update_match_state
from lib.reddit_video import fetch_reddit_goal_video


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
        # Track which goals we've already sent the video for, so we
        # can retry the video lookup on subsequent runs without
        # re-sending the text message.
        # NOTE: these lists only contain short string keys like
        # 'goal_Haaland_36' - never video data or URLs.
        video_pending = state.get('video_pending', [])
        video_sent = state.get('video_sent', [])

        # 1. Send new goal/card text messages
        for g in match['goals']:
            event_key = f"goal_{g['player']}_{g['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_goal({
                    'team': g['team'], 'player': g['player'], 'minute': g['minute'],
                    'home_score': match['home_score'], 'away_score': match['away_score'],
                    'home_team': match['home_team'], 'away_team': match['away_team'],
                }))
                last_events.append(event_key)
                # Queue this goal for video lookup
                if event_key not in video_pending and event_key not in video_sent:
                    video_pending.append(event_key)

        for c in match['cards']:
            event_key = f"card_{c['player']}_{c['minute']}"
            if event_key not in last_events:
                send_message(fmt.format_card({
                    'team': c['team'], 'player': c['player'],
                    'minute': c['minute'], 'detail': c['detail'],
                }))
                last_events.append(event_key)

        # 2. Try to fetch and send videos for any pending goals.
        # Only Reddit is used as a source now - it provides actual
        # goal replay clips via v.redd.it, whereas ESPN's clips were
        # mostly fan-reaction / studio analysis clips.
        still_pending = []
        for event_key in video_pending:
            if event_key in video_sent:
                continue
            # Find the matching goal in match['goals'] to get the
            # player name, minute, and team.
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
                # Goal is no longer in ESPN's data (very old) - give up
                video_sent.append(event_key)
                continue

            # Search r/soccer for a fan-posted v.redd.it clip.
            # This returns a direct .mp4 URL that Telegram downloads
            # server-side. We never download the video ourselves.
            video_url, video_title = fetch_reddit_goal_video(
                player_name, minute_str,
                match['home_team'], match['away_team'],
            )

            if video_url:
                # Pass the URL to Telegram's sendVideo. Telegram's
                # servers download the video from v.redd.it and store
                # it on Telegram's own CDN. We don't keep any copy.
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
                    # Telegram rejected the video - give up
                    video_sent.append(event_key)
                    print(f"Video send failed for goal: {player_name} ({minute_str})")
            else:
                # No clip available yet - keep it pending for the next run
                still_pending.append(event_key)

        # Update state. We only keep short string keys, never video data.
        # Also cap the video_sent list to the last 50 entries so state.json
        # doesn't grow forever as the tournament progresses.
        update_match_state(
            str(match['id']),
            last_events=last_events[-100:],
            video_pending=still_pending,
            video_sent=video_sent[-50:],
        )

    print(f"Event check completed at {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
