#!/usr/bin/env python3
"""Checks live matches for new goals and cards since the last run.

Enhanced: when a new goal is detected, after sending the text goal
message it also looks up ESPN's goal-clips (.mp4 direct URLs) and
forwards the matching clip to the channel via sendVideo.

The video lookup is retried across the next few cron runs (each run is
~1 minute apart) because ESPN's clips typically appear 2-5 minutes
after the goal is scored. We track the goal's video_sent state in
state.json so we don't re-send the same clip.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime, timezone
from lib.api_client import FootballAPIClient
from lib.formatter import PersianFormatter, fa, TEAM_FA, PLAYER_FA
from lib.telegram_sender import send_message, send_video
from lib.state_manager import get_match_state, update_match_state
from lib.goal_video import fetch_goal_video_url
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
        video_pending = state.get('video_pending', [])  # list of event_keys
        video_sent = state.get('video_sent', [])  # list of event_keys

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

        # 2. Try to fetch and send videos for any pending goals
        still_pending = []
        for event_key in video_pending:
            if event_key in video_sent:
                continue
            # Parse the player name back from the event_key
            # Format: goal_{player}_{minute} - but player names can contain underscores
            # so we need to be smarter. Try to find the matching goal in match['goals'].
            player_name = None
            minute_str = None
            for g in match['goals']:
                if f"goal_{g['player']}_{g['minute']}" == event_key:
                    player_name = g['player']
                    minute_str = g['minute']
                    break

            if not player_name:
                # Goal is no longer in ESPN's data (very old) - give up
                video_sent.append(event_key)
                continue

            # Try to find a video clip for this goal.
            # Order of preference:
            #   1. ESPN goal clips (direct .mp4 from media.video-cdn.espn.com)
            #   2. Reddit r/soccer v.redd.it clips (direct .mp4 from v.redd.it)
            video_url = fetch_goal_video_url(match['id'], player_name, g['team'])
            video_source = 'ESPN'
            if not video_url:
                # Fallback: search r/soccer for a fan-posted clip
                reddit_url, reddit_title = fetch_reddit_goal_video(
                    player_name, minute_str,
                    match['home_team'], match['away_team'],
                )
                if reddit_url:
                    video_url = reddit_url
                    video_source = 'Reddit'

            if video_url:
                # Send the video to the channel
                player_fa = fa(player_name, PLAYER_FA)
                team_fa = fa(g['team'], TEAM_FA)
                source_emoji = '📺' if video_source == 'ESPN' else '🎥'
                caption = (
                    f"{source_emoji} ویدیوی گلِ {player_fa} ({team_fa}) - دقیقه {minute_str}\n"
                    f"📊 {fa(match['home_team'], TEAM_FA)} {match['home_score']} - "
                    f"{match['away_score']} {fa(match['away_team'], TEAM_FA)}"
                )
                if send_video(video_url, caption=caption):
                    video_sent.append(event_key)
                    print(f"Video sent for goal: {player_name} ({minute_str}) via {video_source}")
                else:
                    # Telegram rejected the video - give up
                    video_sent.append(event_key)
                    print(f"Video send failed for goal: {player_name} ({minute_str})")
            else:
                # No clip available yet - keep it pending for the next run
                # But limit retries to ~10 minutes (10 cron runs at 1 min each)
                # by tracking when the goal was first detected.
                # For simplicity, we just keep it pending until found or
                # until the match ends (postmatch.py clears active_matches).
                still_pending.append(event_key)

        # Update state
        update_match_state(
            str(match['id']),
            last_events=last_events[-100:],
            video_pending=still_pending,
            video_sent=video_sent[-100:],
        )

    print(f"Event check completed at {datetime.now(timezone.utc).isoformat()}")


if __name__ == '__main__':
    mid = sys.argv[1] if len(sys.argv) > 1 else None
    main(match_id=mid)
